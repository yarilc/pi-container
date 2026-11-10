"""Opt-in idle acceptance, appended after controlled TLS binding fixtures."""
import time

# get() uses verified TLS, Connection: close and a new CONNECT for each request.
# The production proxy admits only one channel, so successful reuse also rules
# out reconnection. Allow closure acknowledgments to settle before the idle gap.
assert get() == b'controlled-production-proxy-ok'
time.sleep(1)
started = time.monotonic()
print('guarded-mux-idle-start seconds=305', flush=True)
time.sleep(305)
assert time.monotonic() - started >= 305
assert get() == b'controlled-production-proxy-ok'
print('guarded-mux-idle-resume-ok', flush=True)
