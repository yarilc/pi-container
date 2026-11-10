/* Link-time component instrumentation. Never build this into the shipped guard.
 * This simulates ABI/syscall results; it does not provide any IPC enforcement. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/statvfs.h>
#include <sys/syscall.h>
#include <unistd.h>
#include "guard_landlock.h"

long __real_syscall(long number, ...);
int __real_prctl(int option, ...);
int __real_open(const char *path, int flags, ...);
int __real_mkdir(const char *path, mode_t mode);
int __real_fstatfs(int fd, struct statfs *result);
int __real_fstatvfs(int fd, struct statvfs *result);

static int matches(const char *value)
{
    const char *fault = getenv("SANDBOX_GUARD_TEST_FAULT");
    return fault && strcmp(fault, value) == 0;
}

static const char *translated(const char *path, char *buffer, size_t size)
{
    const char *root = getenv("SANDBOX_GUARD_TEST_ROOT");
    if (root && !strcmp(path, "/proc/self/mountinfo")) {
        snprintf(buffer, size, "%s/mountinfo", root);
        return buffer;
    }
    if (root && (!strcmp(path, "/") || !strcmp(path, "/tmp") ||
                 !strcmp(path, "/run") || !strcmp(path, "/var/tmp") ||
                 !strcmp(path, "/tmp/sandbox-runtime") ||
                 !strcmp(path, "/run/sandbox-egress") ||
                 !strcmp(path, "/run/sandbox-egress/proxy.sock"))) {
        int length = snprintf(buffer, size, "%s%s", root, path);
        if (length < 0 || (size_t)length >= size)
            _exit(90);
        return buffer;
    }
    return path;
}

int __wrap_open(const char *path, int flags, ...)
{
    char buffer[4096];
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list args;
        va_start(args, flags);
        mode = (mode_t)va_arg(args, int);
        va_end(args);
    }
    return __real_open(translated(path, buffer, sizeof(buffer)), flags, mode);
}

int __wrap_mkdir(const char *path, mode_t mode)
{
    char buffer[4096];
    return __real_mkdir(translated(path, buffer, sizeof(buffer)), mode);
}

int __wrap_fstatfs(int fd, struct statfs *result)
{
    int status = __real_fstatfs(fd, result);
    if (!status)
        result->f_type = matches("filesystem") ? 0 : GUARD_TMPFS_MAGIC;
    return status;
}

int __wrap_fstatvfs(int fd, struct statvfs *result)
{
    int status = __real_fstatvfs(fd, result);
    if (!status && !matches("writable-proxy"))
        result->f_flag |= ST_RDONLY;
    return status;
}

int __wrap_prctl(int option, ...)
{
    if (option == PR_GET_SECCOMP && matches("oci-profile"))
        return 0;
    if ((matches("privileges") && (option == PR_SET_NO_NEW_PRIVS || option == PR_GET_NO_NEW_PRIVS)) ||
        (option == PR_SET_SECCOMP && matches("filter"))) {
        errno = EPERM;
        return -1;
    }
    va_list args;
    va_start(args, option);
    unsigned long a = va_arg(args, unsigned long);
    unsigned long b = va_arg(args, unsigned long);
    unsigned long c = va_arg(args, unsigned long);
    unsigned long d = va_arg(args, unsigned long);
    va_end(args);
    return __real_prctl(option, a, b, c, d);
}

long __wrap_syscall(long number, ...)
{
    static unsigned int rules;
    va_list args;
    va_start(args, number);
    long result = -1;
    errno = EINVAL;
    if (number == SYS_close_range) {
        unsigned int first = va_arg(args, unsigned int);
        unsigned int last = va_arg(args, unsigned int);
        unsigned int flags = va_arg(args, unsigned int);
        if (matches("descriptors")) {
            errno = EPERM;
        } else {
            result = __real_syscall(number, first, last, flags);
        }
    } else if (number == SYS_landlock_create_ruleset) {
        const struct guard_ruleset_attr *attributes = va_arg(args, const void *);
        size_t size = va_arg(args, size_t);
        unsigned long flags = va_arg(args, unsigned long);
        if (!attributes && !size && flags == GUARD_CREATE_RULESET_VERSION) {
            const char *abi = getenv("SANDBOX_GUARD_TEST_ABI");
            if (matches("query")) {
                errno = ENOSYS;
            } else {
                result = abi ? strtol(abi, NULL, 10) : 3;
            }
        } else if (attributes && size == sizeof(*attributes) && flags == 0 &&
                   attributes->handled_access_fs == (GUARD_FS_MAKE_SOCK | GUARD_FS_REFER) && !matches("create")) {
            result = __real_open("/dev/null", O_RDONLY | O_CLOEXEC);
        }
    } else if (number == SYS_landlock_add_rule) {
        int ruleset_fd = va_arg(args, int);
        unsigned long kind = va_arg(args, unsigned long);
        const struct guard_path_attr *rule = va_arg(args, const void *);
        unsigned long flags = va_arg(args, unsigned long);
        uint64_t expected = rules == 0 ? GUARD_FS_REFER : GUARD_FS_MAKE_SOCK;
        if (ruleset_fd >= 3 && kind == GUARD_RULE_PATH_BENEATH && rule &&
            rule->parent_fd >= 3 && rule->allowed_access == expected && flags == 0 &&
            rules < 4 && !matches("rule")) {
            ++rules;
            result = 0;
        }
    } else if (number == SYS_landlock_restrict_self) {
        int ruleset_fd = va_arg(args, int);
        unsigned long flags = va_arg(args, unsigned long);
        unsigned int expected = 4;
        if (ruleset_fd >= 3 && flags == 0 && rules == expected && !matches("restrict")) {
            fputs("COMPONENT MOCK: exact rules accepted; no Landlock enforcement\n", stderr);
            result = 0;
        }
    }
    va_end(args);
    return result;
}
