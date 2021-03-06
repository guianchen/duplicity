# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright 2002 Ben Escoto <ben@emerose.org>
# Copyright 2007 Kenneth Loafman <kenneth@loafman.com>
#
# This file is part of duplicity.
#
# Duplicity is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 2 of the License, or (at your
# option) any later version.
#
# Duplicity is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with duplicity; if not, write to the Free Software Foundation,
# Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA

"""Define some lazy data structures and functions acting on them"""
from __future__ import print_function

import os
from duplicity import log
from duplicity import robust
from duplicity import util


class Iter:
    """Hold static methods for the manipulation of lazy iterators"""

    @staticmethod
    def filter(predicate, iterator):  # @NoSelf
        """Like filter in a lazy functional programming language"""
        for i in iterator:
            if predicate(i):
                yield i

    @staticmethod
    def map(function, iterator):  # @NoSelf
        """Like map in a lazy functional programming language"""
        for i in iterator:
            yield function(i)

    @staticmethod
    def foreach(function, iterator):  # @NoSelf
        """Run function on each element in iterator"""
        for i in iterator:
            function(i)

    @staticmethod
    def cat(*iters):  # @NoSelf
        """Lazily concatenate iterators"""
        for iter in iters:
            for i in iter:
                yield i

    @staticmethod
    def cat2(iter_of_iters):  # @NoSelf
        """Lazily concatenate iterators, iterated by big iterator"""
        for iter in iter_of_iters:
            for i in iter:
                yield i

    @staticmethod
    def empty(iter):  # @NoSelf
        """True if iterator has length 0"""
        for i in iter:  # @UnusedVariable
            return None
        return 1

    @staticmethod
    def equal(iter1, iter2, verbose=None, operator=lambda x, y: x == y):  # @NoSelf
        """True if iterator 1 has same elements as iterator 2

        Use equality operator, or == if it is unspecified.

        """
        for i1 in iter1:
            try:
                i2 = next(iter2)
            except StopIteration:
                if verbose:
                    print("End when i1 = %s" % (i1,))
                return None
            if not operator(i1, i2):
                if verbose:
                    print("%s not equal to %s" % (i1, i2))
                return None
        try:
            i2 = next(iter2)
        except StopIteration:
            return 1
        if verbose:
            print("End when i2 = %s" % (i2,))
        return None

    @staticmethod
    def Or(iter):  # @NoSelf
        """True if any element in iterator is true.  Short circuiting"""
        i = None
        for i in iter:
            if i:
                return i
        return i

    @staticmethod
    def And(iter):  # @NoSelf
        """True if all elements in iterator are true.  Short circuiting"""
        i = 1
        for i in iter:
            if not i:
                return i
        return i

    @staticmethod
    def len(iter):  # @NoSelf
        """Return length of iterator"""
        i = 0
        while 1:
            try:
                next(iter)
            except StopIteration:
                return i
            i = i + 1

    @staticmethod
    def foldr(f, default, iter):  # @NoSelf
        """foldr the "fundamental list recursion operator"?"""
        try:
            next_item = next(iter)
        except StopIteration:
            return default
        return f(next_item, Iter.foldr(f, default, iter))

    @staticmethod
    def foldl(f, default, iter):  # @NoSelf
        """the fundamental list iteration operator.."""
        while 1:
            try:
                next_item = next(iter)
            except StopIteration:
                return default
            default = f(default, next_item)

    @staticmethod
    def multiplex(iter, num_of_forks, final_func=None, closing_func=None):  # @NoSelf
        """Split a single iterater into a number of streams

        The return val will be a list with length num_of_forks, each
        of which will be an iterator like iter.  final_func is the
        function that will be called on each element in iter just as
        it is being removed from the buffer.  closing_func is called
        when all the streams are finished.

        """
        if num_of_forks == 2 and not final_func and not closing_func:
            im2 = IterMultiplex2(iter)
            return (im2.yielda(), im2.yieldb())
        if not final_func:
            final_func = lambda i: None
        if not closing_func:
            closing_func = lambda: None

        # buffer is a list of elements that some iterators need and others
        # don't
        buffer = []

        # buffer[forkposition[i]] is the next element yieled by iterator
        # i.  If it is -1, yield from the original iter
        starting_forkposition = [-1] * num_of_forks
        forkposition = starting_forkposition[:]
        called_closing_func = [None]

        def get_next(fork_num):
            """Return the next element requested by fork_num"""
            if forkposition[fork_num] == -1:
                try:
                    buffer.insert(0, next(iter))
                except StopIteration:
                    # call closing_func if necessary
                    if (forkposition == starting_forkposition and
                            not called_closing_func[0]):
                        closing_func()
                        called_closing_func[0] = None
                    raise StopIteration
                for i in range(num_of_forks):
                    forkposition[i] += 1

            return_val = buffer[forkposition[fork_num]]
            forkposition[fork_num] -= 1

            blen = len(buffer)
            if not (blen - 1) in forkposition:
                # Last position in buffer no longer needed
                assert forkposition[fork_num] == blen - 2
                final_func(buffer[blen - 1])
                del buffer[blen - 1]
            return return_val

        def make_iterator(fork_num):
            while(1):
                yield get_next(fork_num)

        return tuple(map(make_iterator, range(num_of_forks)))


class IterMultiplex2:
    """Multiplex an iterator into 2 parts

    This is a special optimized case of the Iter.multiplex function,
    used when there is no closing_func or final_func, and we only want
    to split it into 2.  By profiling, this is a time sensitive class.

    """
    def __init__(self, iter):
        self.a_leading_by = 0  # How many places a is ahead of b
        self.buffer = []
        self.iter = iter

    def yielda(self):
        """Return first iterator"""
        buf, iter = self.buffer, self.iter
        while(1):
            if self.a_leading_by >= 0:
                # a is in front, add new element
                elem = next(iter)  # exception will be passed
                buf.append(elem)
            else:
                # b is in front, subtract an element
                elem = buf.pop(0)
            self.a_leading_by += 1
            yield elem

    def yieldb(self):
        """Return second iterator"""
        buf, iter = self.buffer, self.iter
        while(1):
            if self.a_leading_by <= 0:
                # b is in front, add new element
                elem = next(iter)  # exception will be passed
                buf.append(elem)
            else:
                # a is in front, subtract an element
                elem = buf.pop(0)
            self.a_leading_by -= 1
            yield elem


class IterTreeReducer:
    """Tree style reducer object for iterator - stolen from rdiff-backup

    The indicies of a RORPIter form a tree type structure.  This class
    can be used on each element of an iter in sequence and the result
    will be as if the corresponding tree was reduced.  This tries to
    bridge the gap between the tree nature of directories, and the
    iterator nature of the connection between hosts and the temporal
    order in which the files are processed.

    This will usually be used by subclassing ITRBranch below and then
    call the initializer below with the new class.

    """
    def __init__(self, branch_class, branch_args):
        """ITR initializer"""
        self.branch_class = branch_class
        self.branch_args = branch_args
        self.index = None
        self.root_branch = branch_class(*branch_args)
        self.branches = [self.root_branch]

    def finish_branches(self, index):
        """Run Finish() on all branches index has passed

        When we pass out of a branch, delete it and process it with
        the parent.  The innermost branches will be the last in the
        list.  Return None if we are out of the entire tree, and 1
        otherwise.

        """
        branches = self.branches
        while 1:
            to_be_finished = branches[-1]
            base_index = to_be_finished.base_index
            if base_index != index[:len(base_index)]:
                # out of the tree, finish with to_be_finished
                to_be_finished.call_end_proc()
                del branches[-1]
                if not branches:
                    return None
                branches[-1].branch_process(to_be_finished)
            else:
                return 1

    def add_branch(self):
        """Return branch of type self.branch_class, add to branch list"""
        branch = self.branch_class(*self.branch_args)
        self.branches.append(branch)
        return branch

    def process_w_branch(self, index, branch, args):
        """Run start_process on latest branch"""
        robust.check_common_error(branch.on_error,
                                  branch.start_process, args)
        if not branch.caught_exception:
            branch.start_successful = 1
        branch.base_index = index

    def Finish(self):
        """Call at end of sequence to tie everything up"""
        while 1:
            to_be_finished = self.branches.pop()
            to_be_finished.call_end_proc()
            if not self.branches:
                break
            self.branches[-1].branch_process(to_be_finished)

    def __call__(self, *args):
        """Process args, where args[0] is current position in iterator

        Returns true if args successfully processed, false if index is
        not in the current tree and thus the final result is
        available.

        Also note below we set self.index after doing the necessary
        start processing, in case there is a crash in the middle.

        """
        index = args[0]
        if self.index is None:
            self.process_w_branch(index, self.root_branch, args)
            self.index = index
            return 1

        if index <= self.index:
            log.Warn(_("Warning: oldindex %s >= newindex %s") %
                     (util.uindex(self.index), util.uindex(index)))
            return 1

        if self.finish_branches(index) is None:
            return None  # We are no longer in the main tree
        last_branch = self.branches[-1]
        if last_branch.start_successful:
            if last_branch.can_fast_process(*args):
                robust.check_common_error(last_branch.on_error,
                                          last_branch.fast_process, args)
            else:
                branch = self.add_branch()
                self.process_w_branch(index, branch, args)
        else:
            last_branch.log_prev_error(index)

        self.index = index
        return 1


class ITRBranch:
    """Helper class for IterTreeReducer above

    There are five stub functions below: start_process, end_process,
    branch_process, fast_process, and can_fast_process.  A class that
    subclasses this one will probably fill in these functions to do
    more.

    """
    base_index = index = None
    finished = None
    caught_exception = start_successful = None

    def call_end_proc(self):
        """Runs the end_process on self, checking for errors"""
        if self.finished or not self.start_successful:
            self.caught_exception = 1

        # Since all end_process does is copy over attributes, might as
        # well run it even if we did get errors earlier.
        robust.check_common_error(self.on_error, self.end_process)

        self.finished = 1

    def start_process(self, *args):
        """Do some initial processing (stub)"""
        pass

    def end_process(self):
        """Do any final processing before leaving branch (stub)"""
        pass

    def branch_process(self, branch):
        """Process a branch right after it is finished (stub)"""
        assert branch.finished
        pass

    def can_fast_process(self, *args):
        """True if object can be processed without new branch (stub)"""
        return None

    def fast_process(self, *args):
        """Process args without new child branch (stub)"""
        pass

    def on_error(self, exc, *args):
        """This is run on any exception in start/end-process"""
        self.caught_exception = 1
        if args and args[0] and isinstance(args[0], tuple):
            filename = os.path.join(*args[0])
        elif self.index:
            filename = os.path.join(*self.index)  # pylint: disable=not-an-iterable
        else:
            filename = "."
        log.Warn(_("Error '%s' processing %s") % (exc, util.fsdecode(filename)),
                 log.WarningCode.cannot_process,
                 util.escape(filename))

    def log_prev_error(self, index):
        """Call function if no pending exception"""
        if not index:
            index_str = "."
        else:
            index_str = os.path.join(*index)
        log.Warn(_("Skipping %s because of previous error") % util.fsdecode(index_str),
                 log.WarningCode.process_skipped,
                 util.escape(index_str))
