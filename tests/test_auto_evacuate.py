import unittest
import mock
from mock import Mock

#setup for import codes which is parent directory.
import os.path
curdir = os.path.abspath(os.path.curdir)
positions = curdir.split(os.path.sep)
parent_dir = os.path.sep.join(positions[:-1])
#print parent_dir

import sys
sys.path.append(parent_dir)
#print sys.path
