/* Additional restriction, stacked on the existing OCI seccomp profile.
 * Linux x86_64 only. Argument checks match the kernel's int truncation. */
#ifndef SANDBOX_GUARD_SECCOMP_H
#define SANDBOX_GUARD_SECCOMP_H
#include <stdint.h>
#include <stddef.h>
#include <sys/socket.h>
#include <sys/syscall.h>

#if !defined(__x86_64__) || defined(__ILP32__)
#error "The guard requires a tested native x86_64 syscall ABI"
#endif

/* Minimal Linux v6.6 UAPI layouts. The pinned musl toolchain intentionally
 * has no linux-headers package; keep these declarations independently auditable.
 * Sources: include/uapi/linux/{filter,seccomp,audit}.h. */
struct sock_filter { uint16_t code; uint8_t jt, jf; uint32_t k; };
struct sock_fprog { unsigned short len; struct sock_filter *filter; };
struct seccomp_data { int nr; uint32_t arch; uint64_t instruction_pointer, args[6]; };
_Static_assert(sizeof(struct sock_filter) == 8, "BPF instruction layout");
_Static_assert(offsetof(struct seccomp_data, args) == 16, "seccomp argument layout");
#define AUDIT_ARCH_X86_64 0xc000003eU
#define SECCOMP_MODE_FILTER 2
#define SECCOMP_RET_ALLOW 0x7fff0000U
#define SECCOMP_RET_ERRNO 0x00050000U
#define BPF_LD 0x00
#define BPF_W 0x00
#define BPF_ABS 0x20
#define BPF_JMP 0x05
#define BPF_JEQ 0x10
#define BPF_JSET 0x40
#define BPF_K 0x00
#define BPF_RET 0x06
#define BPF_ALU 0x04
#define BPF_AND 0x50
#define BPF_STMT(code, k) { (code), 0, 0, (k) }
#define BPF_JUMP(code, k, jt, jf) { (code), (jt), (jf), (k) }

static void install_socket_filter(void)
{
    enum { SOCKET = 11, PAIR = 14, PROTOCOL = 20, ALLOW = 22, DENY = 23 };
    struct sock_filter instructions[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_X86_64, 0, DENY - 2),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, 0x40000000U, DENY - 4, 0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_socket, SOCKET - 5, 0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_socketpair, PAIR - 6, 0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_io_uring_setup, DENY - 7, 0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_io_uring_enter, DENY - 8, 0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_io_uring_register, DENY - 9, 0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_pidfd_getfd, DENY - 10, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AF_INET, ALLOW - 13, 0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AF_INET6, ALLOW - 14, DENY - 14),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AF_UNIX, 0, DENY - 16),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[1])),
        BPF_STMT(BPF_ALU | BPF_AND | BPF_K, ~(SOCK_CLOEXEC | SOCK_NONBLOCK)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SOCK_STREAM, PROTOCOL - 19, 0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SOCK_SEQPACKET, PROTOCOL - 20, DENY - 20),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[2])),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, ALLOW - 22, DENY - 22),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
    };
    _Static_assert(sizeof(instructions) / sizeof(instructions[0]) == DENY + 1,
                   "Filter jump layout");
    struct sock_fprog program = {
        .len = sizeof(instructions) / sizeof(instructions[0]),
        .filter = instructions,
    };
    if (prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, (unsigned long)&program, 0UL, 0UL) < 0)
        fail("additional seccomp filter installation");
}
#endif
