"""Prevent two processes from executing the same persisted queue."""
import os


class WorkspaceLease:
    def __init__(self, path):
        self.file = open(path, 'a+b')
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError('This workspace already has a job worker process') from None

    def close(self):
        if not self.file.closed:
            self.file.close()
