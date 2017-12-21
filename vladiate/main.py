try:
    from Queue import Empty
except ImportError:
    from queue import Empty
from multiprocessing import Pool, Queue
from vladiate import Vlad
from vladiate import logs

import os
import sys
import inspect
from argparse import ArgumentParser
from pkg_resources import get_distribution


def parse_args():
    """
    Handle command-line arguments with argparse.ArgumentParser
    Return list of arguments, largely for use in `parse_arguments`.
    """

    # Initialize
    parser = ArgumentParser(
        description="vladiate [options] [VladClass [VladClass2 ... ]]")

    parser.add_argument('vlads', metavar='vlads', type=str, nargs='*',
                        help='A list of Vlad classes to validate')

    # Specify the vladfile to be something other than vladfile.py
    parser.add_argument(
        '-f', '--vladfile',
        dest='vladfile',
        default='vladfile',
        help="Python module to import, e.g. '../other.py'. Default: vladfile")

    # List vladiate commands found in loaded vladiate files/source files
    parser.add_argument(
        '-l', '--list',
        action='store_true',
        dest='list_commands',
        default=False,
        help="Show list of possible vladiate classes and exit")

    # Version number
    parser.add_argument(
        '-V', '--version',
        action='store_true',
        dest='show_version',
        default=False,
        help="show program's version number and exit")

    # Maximum number of processes to attempt to use
    parser.add_argument(
        '-p', '--processes',
        dest='processes',
        default=1,
        type=int,
        help="attempt to use this number of processes")

    return parser.parse_args()


def is_vlad(tup):
    """
    Takes (name, object) tuple, returns True if it's a public Vlad subclass.
    """
    name, item = tup
    return bool(
        inspect.isclass(item) and issubclass(item, Vlad) and
        hasattr(item, "source") and getattr(item, "source") and
        hasattr(item, "validators") and not name.startswith('_'))


def _is_package(path):
    """
    Is the given path a Python package?
    """
    return (
        os.path.isdir(path) and
        os.path.exists(os.path.join(path, '__init__.py'))
    )


def find_vladfile(vladfile, path='.'):
    """
    Attempt to locate a vladfile, either explicitly or by searching parent dirs.
    """
    assert os.path.isdir(path)
    # Obtain env value
    names = [vladfile]
    # Create .py version if necessary
    if not names[0].endswith('.py'):
        names += [names[0] + '.py']
    # Does the name contain path elements?
    if os.path.dirname(names[0]):
        # If so, expand home-directory markers and test for existence
        for name in names:
            expanded = os.path.expanduser(name)
            if os.path.exists(expanded):
                if name.endswith('.py') or _is_package(expanded):
                    return os.path.abspath(expanded)
    else:
        for name in names:
            joined = os.path.join(path, name)
            if os.path.exists(joined):
                if name.endswith('.py') or _is_package(joined):
                    return os.path.abspath(joined)
    # Implicit 'return None' if nothing was found


def load_vladfile(path):
    """
    Import given vladfile path and return (docstring, callables).
    Specifically, the vladfile's ``__doc__`` attribute (a string) and a
    dictionary of ``{'name': callable}`` containing all callables which pass
    the "is a vlad" test.
    """
    # Get directory and vladfile name
    directory, vladfile = os.path.split(path)
    # If the directory isn't in the PYTHONPATH, add it so our import will work
    added_to_path = False
    index = None
    if directory not in sys.path:
        sys.path.insert(0, directory)
        added_to_path = True
    # If the directory IS in the PYTHONPATH, move it to the front temporarily,
    # otherwise other vladfiles -- like vlads's own -- may scoop the intended
    # one.
    else:
        i = sys.path.index(directory)
        if i != 0:
            # Store index for later restoration
            index = i
            # Add to front, then remove from original position
            sys.path.insert(0, directory)
            del sys.path[i + 1]
    # Perform the import (trimming off the .py)
    imported = __import__(os.path.splitext(vladfile)[0])
    # Remove directory from path if we added it ourselves (just to be neat)
    if added_to_path:
        del sys.path[0]
    # Put back in original index if we moved it
    if index is not None:
        sys.path.insert(index + 1, directory)
        del sys.path[0]
    # Return our two-tuple
    vlads = dict(filter(is_vlad, vars(imported).items()))
    return imported.__doc__, vlads


def _vladiate(vlad):
    global result_queue
    result_queue.put(vlad(vlad.source, validators=vlad.validators).validate())


result_queue = Queue()


def main():
    arguments = parse_args()
    logger = logs.logger

    if arguments.show_version:
        print("Vladiate %s" % (get_distribution('vladiate').version, ))
        return os.EX_OK

    vladfile = find_vladfile(arguments.vladfile)
    if not vladfile:
        logger.error(
            "Could not find any vladfile! Ensure file ends in '.py' and see "
            "--help for available options."
        )
        return os.EX_NOINPUT

    docstring, vlads = load_vladfile(vladfile)

    if arguments.list_commands:
        logger.info("Available vlads:")
        for name in vlads:
            logger.info("    " + name)
        return os.EX_OK

    if not vlads:
        logger.error("No vlad class found!")
        return os.EX_NOINPUT

    # make sure specified vlad exists
    if arguments.vlads:
        missing = set(arguments.vlads) - set(vlads.keys())
        if missing:
            logger.error("Unknown vlad(s): %s\n" % (", ".join(missing)))
            return os.EX_UNAVAILABLE
        else:
            names = set(arguments.vlads) & set(vlads.keys())
            vlad_classes = [vlads[n] for n in names]
    else:
        vlad_classes = vlads.values()

    # validate all the vlads, and collect the validations for a good exit
    # return code
    if arguments.processes == 1:
        for vlad in vlad_classes:
            vlad(source=vlad.source).validate()

    else:
        proc_pool = Pool(
            arguments.processes
            if arguments.processes <= len(vlad_classes)
            else len(vlad_classes)
        )
        proc_pool.map(_vladiate, vlad_classes)
        try:
            if not result_queue.get_nowait():
                return os.EX_DATAERR
        except Empty:
            pass
        return os.EX_OK


def run(name):
    if name == '__main__':
        exit(main())


run(__name__)
