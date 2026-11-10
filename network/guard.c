#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/statvfs.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/syscall.h>
#include <unistd.h>

#include "guard_landlock.h"

#define GUARD_REVISION "abi3-seccomp-mux-v1"
#define GUARD_PROXY_PATH "/run/sandbox-egress/proxy.sock"
#define GUARD_RUNTIME_PATH "/tmp/sandbox-runtime"

/* The bootstrap has no interpreter, NSS lookup, locale initialization, dynamic
 * loading, runtime policy hooks or environment-selected enforcement settings. */
static void fail(const char *stage)
{
    int saved_errno = errno;
    char message[256];
    int size = snprintf(message, sizeof(message),
                        "sandbox-egress-guard: %s failed (errno=%d); restricted startup stopped\n",
                        stage, saved_errno);
    if (size > 0 && (size_t)size < sizeof(message)) {
        const char *cursor = message;
        while (size > 0) {
            ssize_t written = write(STDERR_FILENO, cursor, (size_t)size);
            if (written < 0 && errno == EINTR)
                continue;
            if (written <= 0)
                break;
            cursor += written;
            size -= (int)written;
        }
    }
    _exit(78);
}

#include "guard_seccomp.h"

static int ordinary_stdio(int fd)
{
    struct stat info, null_info;
    if (fstat(fd, &info) < 0)
        return 0;
    if (S_ISREG(info.st_mode)) {
        struct statfs filesystem;
        int flags = fcntl(fd, F_GETFL);
        if (flags < 0 || (flags & O_PATH) || fstatfs(fd, &filesystem) < 0)
            return 0;
        /* Linux v6.6 magic.h: namespace/process and anonymous-inode handles
         * are capabilities, not ordinary redirected files. */
        unsigned long kind = (unsigned long)filesystem.f_type;
        return kind != 0x6e736673UL && kind != 0x9fa0UL &&
               kind != 0x62656572UL && kind != 0x09041934UL;
    }
    if (S_ISFIFO(info.st_mode))
        return 1;
    if (!S_ISCHR(info.st_mode))
        return 0;
    if (isatty(fd))
        return 1;
    /* /dev/null is the ordinary non-interactive stdin/output sink. */
    return stat("/dev/null", &null_info) == 0 && S_ISCHR(null_info.st_mode) &&
           info.st_rdev == null_info.st_rdev;
}

static void prepare_descriptors(void)
{
    /* Do not send diagnostics over an unexpected socket/device on stderr. */
    if (!ordinary_stdio(STDERR_FILENO))
        _exit(78);
    for (int fd = 0; fd < 2; ++fd) {
        if (!ordinary_stdio(fd)) {
            errno = EPERM;
            fail("standard I/O validation");
        }
    }
    if (syscall(SYS_close_range, 3U, ~0U, 0U) < 0)
        fail("descriptor cleanup");
}

static long query_abi(void)
{
    long abi = syscall(SYS_landlock_create_ruleset, NULL, (size_t)0,
                       (unsigned long)GUARD_CREATE_RULESET_VERSION);
    if (abi < 0)
        fail("Landlock ABI query");
    if (abi < GUARD_REQUIRED_ABI) {
        char message[160];
        int size = snprintf(message, sizeof(message),
                            "sandbox-egress-guard: Landlock ABI %ld is unsupported; require ABI >= %d\n",
                            abi, GUARD_REQUIRED_ABI);
        if (size > 0 && (size_t)size < sizeof(message)) {
            ssize_t written = write(STDERR_FILENO, message, (size_t)size);
            (void)written;
        }
        _exit(78);
    }
    return abi;
}

static void add_path(int ruleset_fd, const char *path, uint64_t access,
                     int directory, int private_tmpfs)
{
    int flags = O_PATH | O_CLOEXEC | O_NOFOLLOW;
    if (directory)
        flags |= O_DIRECTORY;
    int fd = open(path, flags);
    if (fd < 0)
        fail("rule object open");
    struct stat info;
    if (fstat(fd, &info) < 0)
        fail("rule object metadata");
    if ((directory && !S_ISDIR(info.st_mode)) ||
        (!directory && (!S_ISSOCK(info.st_mode) || info.st_uid != getuid() ||
                        (info.st_mode & 0077) != 0))) {
        errno = EPERM;
        fail("rule object identity");
    }
    if (private_tmpfs) {
        struct statfs filesystem;
        if (fstatfs(fd, &filesystem) < 0)
            fail("private IPC filesystem query");
        if ((unsigned long)filesystem.f_type != GUARD_TMPFS_MAGIC) {
            errno = EPERM;
            fail("private IPC filesystem validation");
        }
    }
    if (!directory) {
        struct statvfs filesystem;
        if (fstatvfs(fd, &filesystem) < 0)
            fail("proxy mount query");
        if (!(filesystem.f_flag & ST_RDONLY)) {
            errno = EPERM;
            fail("proxy read-only mount validation");
        }
    }
    const struct guard_path_attr rule = {
        .allowed_access = access,
        .parent_fd = fd,
    };
    if (syscall(SYS_landlock_add_rule, ruleset_fd,
                (unsigned long)GUARD_RULE_PATH_BENEATH, &rule, 0UL) < 0)
        fail("Landlock path rule installation");
    if (close(fd) < 0)
        fail("rule descriptor cleanup");
}

/* Use a held directory descriptor so pathname substitution cannot redirect the
 * connect. The operator-owned transport directory is immutable to the agent. */
static int connect_proxy(void)
{
    int directory = open("/run/sandbox-egress", O_PATH | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (directory < 0)
        fail("proxy directory open");
    struct stat parent, before, after;
    struct statvfs filesystem;
    if (fstat(directory, &parent) < 0 || fstatvfs(directory, &filesystem) < 0 ||
        fstatat(directory, "proxy.sock", &before, AT_SYMLINK_NOFOLLOW) < 0)
        fail("proxy metadata");
    if (parent.st_uid != getuid() || (parent.st_mode & 0077) ||
        !S_ISSOCK(before.st_mode) || before.st_uid != getuid() ||
        (before.st_mode & 0077) || !(filesystem.f_flag & ST_RDONLY)) {
        errno = EPERM;
        fail("proxy identity/read-only mount validation");
    }
    int channel = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (channel < 0)
        fail("proxy channel creation");
    struct sockaddr_un address = { .sun_family = AF_UNIX };
    int length = snprintf(address.sun_path, sizeof(address.sun_path),
                          "/proc/self/fd/%d/proxy.sock", directory);
    if (length < 0 || (size_t)length >= sizeof(address.sun_path)) {
        errno = ENAMETOOLONG;
        fail("proxy channel address");
    }
    /* The session proxy is already listening; do not block on a full backlog. */
    if (fcntl(channel, F_SETFL, O_NONBLOCK) < 0 ||
        connect(channel, (struct sockaddr *)&address, sizeof(address)) < 0)
        fail("proxy channel connection");
    if (fstatat(directory, "proxy.sock", &after, AT_SYMLINK_NOFOLLOW) < 0 ||
        before.st_dev != after.st_dev || before.st_ino != after.st_ino) {
        errno = EPERM;
        fail("proxy identity changed");
    }
    if (close(directory) < 0)
        fail("proxy directory cleanup");
    if (channel != 3) {
        if (dup3(channel, 3, O_CLOEXEC) < 0 || close(channel) < 0)
            fail("proxy descriptor preparation");
    }
    /* The provider entrypoint consumes fd 3; never accept an environment-chosen
     * inherited descriptor. The relay closes it before application exec. */
    if (fcntl(3, F_SETFD, 0) < 0)
        fail("proxy descriptor inheritance");
    return 3;
}

/* Validate the actual OCI mount layout, not only host-selected path strings.
 * A nested host directory must never inherit a private tmpfs MAKE_SOCK grant. */
static void verify_mount_layout(int provider)
{
    int descriptor = open("/proc/self/mountinfo", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (descriptor < 0)
        fail("mount layout open");
    FILE *mounts = fdopen(descriptor, "r");
    if (!mounts)
        fail("mount layout stream");
    char line[8192], target[4096];
    unsigned int roots = 0;
    while (fgets(line, sizeof(line), mounts)) {
        if (!strchr(line, '\n') || sscanf(line, "%*s %*s %*s %*s %4095s", target) != 1) {
            errno = EINVAL;
            fail("mount layout parsing");
        }
        if (!strcmp(target, "/tmp")) roots |= 1;
        if (!strcmp(target, "/run")) roots |= 2;
        if (!strcmp(target, "/var/tmp")) roots |= 4;
        if (strncmp(target, "/tmp/", 5) && strncmp(target, "/run/", 5) &&
            strncmp(target, "/var/tmp/", 9))
            continue;
        if (provider && !strcmp(target, "/run/sandbox-egress"))
            continue; /* connect_proxy separately verifies owner/mode/read-only. */
        if (!strcmp(target, "/run/.containerenv")) {
            struct stat info;
            if (lstat(target, &info) == 0 && S_ISREG(info.st_mode))
                continue; /* Engine metadata file, not an IPC hierarchy. */
        }
        errno = EPERM;
        fail("nested private IPC mount validation");
    }
    if (ferror(mounts) || roots != 7) {
        errno = EPERM;
        fail("private IPC mount roots");
    }
    if (fclose(mounts))
        fail("mount layout cleanup");
}

static void prepare_runtime(void)
{
    if (mkdir(GUARD_RUNTIME_PATH, 0700) < 0 && errno != EEXIST)
        fail("private runtime directory creation");
    int fd = open(GUARD_RUNTIME_PATH, O_PATH | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0)
        fail("private runtime directory open");
    struct stat info;
    struct statfs filesystem;
    if (fstat(fd, &info) < 0 || fstatfs(fd, &filesystem) < 0)
        fail("private runtime directory metadata");
    if (info.st_uid != getuid() || (info.st_mode & 0777) != 0700 ||
        (unsigned long)filesystem.f_type != GUARD_TMPFS_MAGIC) {
        errno = EPERM;
        fail("private runtime directory validation");
    }
    if (close(fd) < 0)
        fail("runtime descriptor cleanup");
}

int main(int argc, char **argv)
{
    if (argc == 2 && strcmp(argv[1], "--version") == 0) {
        puts("sandbox-egress-guard " GUARD_REVISION " required-abi=3 uapi=linux-v6.6 seccomp=native-x86_64 mux=1");
        return 0;
    }
    int probe = argc == 2 && strcmp(argv[1], "--probe") == 0;
    int provider = argc >= 4 && strcmp(argv[1], "--provider") == 0;
    if (!probe && (argc < 4 || (!provider && strcmp(argv[1], "--offline") != 0) ||
                   strcmp(argv[2], "--") != 0 || argv[3][0] != '/')) {
        fputs("Usage: sandbox-egress-guard --version | --probe | (--offline|--provider) -- /absolute/program [args...]\n", stderr);
        return 64;
    }
    prepare_descriptors();
    long abi = query_abi();
    if (probe) {
        printf("Landlock ABI %ld; required >= %d; query-only, enforcement unverified\n",
               abi, GUARD_REQUIRED_ABI);
        return 0;
    }
    if (prctl(PR_GET_SECCOMP, 0UL, 0UL, 0UL, 0UL) != 2) {
        errno = EPERM;
        fail("existing OCI seccomp validation");
    }
    verify_mount_layout(provider);
    if (provider)
        (void)connect_proxy();
    prepare_runtime();
    if (prctl(PR_SET_NO_NEW_PRIVS, 1UL, 0UL, 0UL, 0UL) < 0 ||
        prctl(PR_GET_NO_NEW_PRIVS, 0UL, 0UL, 0UL, 0UL) != 1)
        fail("no_new_privs");
    const struct guard_ruleset_attr attributes = {
        .handled_access_fs = GUARD_FS_MAKE_SOCK | GUARD_FS_REFER,
    };
    int ruleset_fd = (int)syscall(SYS_landlock_create_ruleset, &attributes,
                                   sizeof(attributes), 0UL);
    if (ruleset_fd < 0)
        fail("Landlock ruleset creation");
    /* A root REFER grant preserves ordinary cross-directory file operations;
     * it grants neither socket creation nor external endpoint resolution. */
    add_path(ruleset_fd, "/", GUARD_FS_REFER, 1, 0);
    add_path(ruleset_fd, "/tmp", GUARD_FS_MAKE_SOCK, 1, 1);
    add_path(ruleset_fd, "/run", GUARD_FS_MAKE_SOCK, 1, 1);
    add_path(ruleset_fd, "/var/tmp", GUARD_FS_MAKE_SOCK, 1, 1);
    if (syscall(SYS_landlock_restrict_self, ruleset_fd, 0UL) < 0)
        fail("Landlock enforcement");
    if (close(ruleset_fd) < 0)
        fail("ruleset descriptor cleanup");
    install_socket_filter();
    if (setenv("XDG_RUNTIME_DIR", GUARD_RUNTIME_PATH, 1) < 0)
        fail("private runtime environment");
    fprintf(stderr, "sandbox-egress-guard: enforced revision=%s abi=%ld\n", GUARD_REVISION, abi);
    execv(argv[3], &argv[3]);
    fail("application exec");
}
