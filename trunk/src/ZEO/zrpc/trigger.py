##############################################################################
#
# Copyright (c) 2001, 2002 Zope Corporation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.0 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE
#
##############################################################################

import asyncore
import os
import socket
import thread

if os.name == 'posix':

    class trigger(asyncore.file_dispatcher):

        "Wake up a call to select() running in the main thread"

        # This is useful in a context where you are using Medusa's I/O
        # subsystem to deliver data, but the data is generated by another
        # thread.  Normally, if Medusa is in the middle of a call to
        # select(), new output data generated by another thread will have
        # to sit until the call to select() either times out or returns.
        # If the trigger is 'pulled' by another thread, it should immediately
        # generate a READ event on the trigger object, which will force the
        # select() invocation to return.

        # A common use for this facility: letting Medusa manage I/O for a
        # large number of connections; but routing each request through a
        # thread chosen from a fixed-size thread pool.  When a thread is
        # acquired, a transaction is performed, but output data is
        # accumulated into buffers that will be emptied more efficiently
        # by Medusa. [picture a server that can process database queries
        # rapidly, but doesn't want to tie up threads waiting to send data
        # to low-bandwidth connections]

        # The other major feature provided by this class is the ability to
        # move work back into the main thread: if you call pull_trigger()
        # with a thunk argument, when select() wakes up and receives the
        # event it will call your thunk from within that thread.  The main
        # purpose of this is to remove the need to wrap thread locks around
        # Medusa's data structures, which normally do not need them.  [To see
        # why this is true, imagine this scenario: A thread tries to push some
        # new data onto a channel's outgoing data queue at the same time that
        # the main thread is trying to remove some]

        def __init__(self):
            r, w = self._fds = os.pipe()
            self.trigger = w
            asyncore.file_dispatcher.__init__(self, r)
            self.lock = thread.allocate_lock()
            self.thunks = []
            self._closed = 0

        # Override the asyncore close() method, because it seems that
        # it would only close the r file descriptor and not w.  The
        # constructor calls file_dispatcher.__init__ and passes r,
        # which would get stored in a file_wrapper and get closed by
        # the default close.  But that would leave w open...

        def close(self):
            if not self._closed:
                self._closed = 1
                self.del_channel()
                for fd in self._fds:
                    os.close(fd)
                self._fds = []

        def __repr__(self):
            return '<select-trigger (pipe) at %x>' % id(self)

        def readable(self):
            return 1

        def writable(self):
            return 0

        def handle_connect(self):
            pass

        def handle_close(self):
            self.close()

        def pull_trigger(self, thunk=None):
            if thunk:
                self.lock.acquire()
                try:
                    self.thunks.append(thunk)
                finally:
                    self.lock.release()
            os.write(self.trigger, 'x')

        def handle_read(self):
            try:
                self.recv(8192)
            except socket.error:
                return
            self.lock.acquire()
            try:
                for thunk in self.thunks:
                    try:
                        thunk()
                    except:
                        nil, t, v, tbinfo = asyncore.compact_traceback()
                        print ('exception in trigger thunk:'
                               ' (%s:%s %s)' % (t, v, tbinfo))
                self.thunks = []
            finally:
                self.lock.release()

else:

    # XXX Should define a base class that has the common methods and
    # then put the platform-specific in a subclass named trigger.

    # win32-safe version

    HOST = '127.0.0.1'
    MINPORT = 19950
    NPORTS = 50

    class trigger(asyncore.dispatcher):

        portoffset = 0

        def __init__(self):
            a = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            w = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            # set TCP_NODELAY to true to avoid buffering
            w.setsockopt(socket.IPPROTO_TCP, 1, 1)

            # tricky: get a pair of connected sockets
            for i in range(NPORTS):
                trigger.portoffset = (trigger.portoffset + 1) % NPORTS
                port = MINPORT + trigger.portoffset
                address = (HOST, port)
                try:
                    a.bind(address)
                except socket.error:
                    continue
                else:
                    break
            else:
                raise RuntimeError, 'Cannot bind trigger!'

            a.listen(1)
            w.setblocking(0)
            try:
                w.connect(address)
            except:
                pass
            r, addr = a.accept()
            a.close()
            w.setblocking(1)
            self.trigger = w

            asyncore.dispatcher.__init__(self, r)
            self.lock = thread.allocate_lock()
            self.thunks = []
            self._trigger_connected = 0

        def __repr__(self):
            return '<select-trigger (loopback) at %x>' % id(self)

        def readable(self):
            return 1

        def writable(self):
            return 0

        def handle_connect(self):
            pass

        def pull_trigger(self, thunk=None):
            if thunk:
                self.lock.acquire()
                try:
                    self.thunks.append(thunk)
                finally:
                    self.lock.release()
            self.trigger.send('x')

        def handle_read(self):
            try:
                self.recv(8192)
            except socket.error:
                return
            self.lock.acquire()
            try:
                for thunk in self.thunks:
                    try:
                        thunk()
                    except:
                        nil, t, v, tbinfo = asyncore.compact_traceback()
                        print ('exception in trigger thunk:'
                               ' (%s:%s %s)' % (t, v, tbinfo))
                self.thunks = []
            finally:
                self.lock.release()
