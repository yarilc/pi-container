/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
/* Minimal ABI declarations from Linux v6.6 include/uapi/linux/landlock.h.
 * Keep the required rights explicit; never mask them for older kernels. */
#ifndef SANDBOX_GUARD_LANDLOCK_H
#define SANDBOX_GUARD_LANDLOCK_H

#include <stdint.h>

#define GUARD_REQUIRED_ABI 3
#define GUARD_CREATE_RULESET_VERSION (1U << 0)
#define GUARD_RULE_PATH_BENEATH 1
#define GUARD_FS_MAKE_SOCK (1ULL << 9)
#define GUARD_FS_REFER (1ULL << 13)
#define GUARD_TMPFS_MAGIC 0x01021994UL

struct guard_ruleset_attr {
    uint64_t handled_access_fs;
};

struct guard_path_attr {
    uint64_t allowed_access;
    int32_t parent_fd;
} __attribute__((packed));

_Static_assert(sizeof(struct guard_ruleset_attr) == 8, "Landlock ruleset layout");
_Static_assert(sizeof(struct guard_path_attr) == 12, "Landlock path rule layout");

#endif
