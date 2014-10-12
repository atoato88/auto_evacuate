import sys, os
testdir = os.path.dirname(__file__)
srcdir = '../'
sys.path.insert(0, os.path.abspath(os.path.join(testdir, srcdir)))

import unittest
import mox
import auto_evacuate
import ConfigParser
import optparse

class AutoEvacuateTest(unittest.TestCase):

  def setUp(self):
    self.mox = mox.Mox()

  def tearDown(self):
    self.mox.UnsetStubs()

  def test_parse_args_OK(self):
    self.mox.StubOutWithMock(optparse.OptionParser, 'parse_args')
    a = optparse.Values()
    a.dry_run = True
    optparse.OptionParser().parse_args().AndReturn( (a, ['111', 'dummy test host']) )
    self.mox.ReplayAll()
    auto_evacuate.parse_args()
    self.mox.VerifyAll()

  def test_parse_args_NG(self):
    self.mox.CreateMock(optparse.OptionParser)
    self.mox.StubOutWithMock(optparse.OptionParser, 'parse_args')
    a = optparse.Values()
    a.dry_run = True
    optparse.OptionParser.parse_args().AndReturn( (a, []) )
    self.mox.ReplayAll()
    with self.assertRaises(SystemExit):
      auto_evacuate.parse_args()
    self.mox.VerifyAll()

  def test_load_config_OK(self):
    self.mox.ReplayAll()
    ret = auto_evacuate.load_config()
    print ret
    self.mox.VerifyAll()

if __name__ == '__main__':
  unittest.main()

