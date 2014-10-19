import sys, os
testdir = os.path.dirname(__file__)
srcdir = '../'
sys.path.insert(0, os.path.abspath(os.path.join(testdir, srcdir)))

import unittest
import mox
import auto_evacuate
import ConfigParser
import optparse
import pyzabbix
from pyzabbix import ZabbixAPI
from novaclient.v1_1.client import Client
import novaclient.exceptions
import syslog
import time

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
    #print ret
    self.mox.VerifyAll()

  def test_load_config_OK_with_zabbix(self):
    self.mox.StubOutWithMock(ConfigParser.ConfigParser, 'getboolean')
    ConfigParser.ConfigParser().getboolean(mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(True)
    # above is dummy for ConfigParser.ConfigParser().getboolean('DEFAULT', 'evacuate_with_shared_storage').AndReturn(True)
    ConfigParser.ConfigParser().getboolean('DEFAULT', 'zabbix_comment_update').AndReturn(True)
    ConfigParser.ConfigParser().getboolean(mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(True)
    # above is dummy for ConfigParser.ConfigParser().getboolean('DEFAULT', 'ignore_zabbix_api_connection').AndReturn(True)

    self.mox.StubOutWithMock(auto_evacuate, 'get_zabbix_api')
    auto_evacuate.get_zabbix_api().AndReturn('dummy return')

    self.mox.ReplayAll()
    ret = auto_evacuate.load_config()
    self.assertEqual(ret['zapi'], 'dummy return')
    self.mox.VerifyAll()

  def test_acknowledge_OK_without_zabbix(self):
    self.mox.StubOutWithMock(auto_evacuate, 'conf')
    auto_evacuate.conf['zabbix_comment_update'].AndReturn(False)

    self.mox.ReplayAll()
    auto_evacuate.acknowledge('dummy zabbix id', 'dummy message')
    self.mox.VerifyAll()

  def test_acknowledge_OK_with_zabbix(self):
    self.mox.StubOutWithMock(auto_evacuate, 'conf')
    auto_evacuate.conf['zabbix_comment_update'].AndReturn(True)
    auto_evacuate.conf['zabbix_comment_update'].AndReturn(True)
    auto_evacuate.conf['ignore_zabbix_api_connection'].AndReturn(True)
    zapi = mox.MockAnything()
    zapi.event = mox.MockAnything()
    zapi.event.acknowledge(mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(None)

    self.mox.ReplayAll()
    auto_evacuate.acknowledge('dummy zabbix id', 'dummy message')
    self.mox.VerifyAll()

  def test_acknowledge_NG_with_zabbix2(self):
    self.mox.StubOutWithMock(auto_evacuate, 'conf')
    auto_evacuate.conf['zabbix_comment_update'].AndReturn(True)
    auto_evacuate.conf['zabbix_comment_update'].AndReturn(True)
    auto_evacuate.conf['ignore_zabbix_api_connection'].AndReturn(False)
    zapi = mox.MockAnything()
    zapi.event = mox.MockAnything()
    zapi.event.acknowledge(mox.IgnoreArg(), mox.IgnoreArg()).AndRaise(Exception('dummy exception'))

    self.mox.ReplayAll()
    with self.assertRaises(Exception):
      auto_evacuate.acknowledge('dummy zabbix id', 'dummy message')
    self.mox.VerifyAll()

  def test_get_zabbix_api_OK(self):
    self.mox.StubOutWithMock(auto_evacuate, 'conf')
    self.mox.StubOutWithMock(pyzabbix, 'ZabbixAPI')
    self.mox.StubOutWithMock(ZabbixAPI, 'login')
    # zapi_mock is OK in anyone below three options.
    #zapi_mock = mox.MockAnything()
    #zapi_mock = self.mox.CreateMock(ZabbixAPI)
    zapi_mock = ZabbixAPI('http://dummy.example.com')

    # mockking login function is ok below too.
    #self.mox.StubOutWithMock(zapi_mock, 'login')

    auto_evacuate.conf['zabbix_comment_update'].AndReturn(True)
    auto_evacuate.conf['zabbix_url'].AndReturn('http://dummy.example.com')
    pyzabbix.ZabbixAPI('http://dummy.example.com').AndReturn(zapi_mock)
    auto_evacuate.conf['zabbix_user'].AndReturn('user')
    auto_evacuate.conf['zabbix_password'].AndReturn('password')
    zapi_mock.login(mox.IgnoreArg(), mox.IgnoreArg())

    self.mox.ReplayAll()
    auto_evacuate.get_zabbix_api()
    self.mox.VerifyAll()

  def test_get_zabbix_api_NG(self):
    self.mox.StubOutWithMock(auto_evacuate, 'conf')
    #self.mox.StubOutWithMock(pyzabbix, 'ZabbixAPI')
    self.mox.StubOutWithMock(ZabbixAPI, '__init__')
    self.mox.StubOutWithMock(ZabbixAPI, 'login')
    # zapi_mock is OK in anyone below three options.
    zapi_mock = mox.MockAnything()
    #zapi_mock = self.mox.CreateMock(ZabbixAPI)
    #zapi_mock = ZabbixAPI('http://dummy.example.com')
    self.mox.StubOutWithMock(syslog, 'syslog')

    auto_evacuate.conf['zabbix_comment_update'].AndReturn(True)
    auto_evacuate.conf['zabbix_url'].AndReturn('dummy url')
    #pyzabbix.ZabbixAPI('dummy url').AndReturn(zapi_mock)
    ZabbixAPI.__init__('dummy url')
    auto_evacuate.conf['zabbix_user'].AndReturn('user')
    auto_evacuate.conf['zabbix_password'].AndReturn('password')
    zapi_mock.login(mox.IgnoreArg(), mox.IgnoreArg()).AndRaise(Exception('dummy exception'))
    syslog.syslog(syslog.LOG_ERR, mox.IgnoreArg())
    syslog.syslog(syslog.LOG_ERR, mox.IgnoreArg())

    self.mox.ReplayAll()
    auto_evacuate.get_zabbix_api()
    self.mox.VerifyAll()

  def test_get_novaclient_OK(self):
    self.mox.StubOutWithMock(auto_evacuate, 'conf')
    #self.mox.StubOutWithMock(novaclient.v1_1.client, 'Client')
    self.mox.StubOutWithMock(Client, '__init__')
    nova_mock = mox.MockAnything()
    #nova_mock = self.mox.CreateMock(Client)
    #nova_mock = Client('user', 'password', 'tenant', 'auth_url')

    auto_evacuate.conf['openstack_user'].AndReturn('user')
    auto_evacuate.conf['openstack_password'].AndReturn('password')
    auto_evacuate.conf['openstack_tenant'].AndReturn('tenant')
    auto_evacuate.conf['openstack_auth_url'].AndReturn('auth_url')
    #novaclient.v1_1.client.Client('user', 'password', 'tenant', 'auth_url').AndReturn(nova_mock)
    Client.__init__('user', 'password', 'tenant', 'auth_url')

    self.mox.ReplayAll()
    auto_evacuate.get_novaclient()
    self.mox.VerifyAll()

  def test_get_target_vms_OK(self):
    nova_client = mox.MockAnything()
    self.mox.StubOutWithMock(nova_client, 'servers')
    self.mox.StubOutWithMock(nova_client.servers, 'list')
    self.mox.StubOutWithMock(auto_evacuate, 'acknowledge')
    vm = mox.MockAnything()
    vm.__dict__['OS-EXT-STS:vm_state']='active'
    vm.id='123456789'
    vms=[]
    vms.append(vm)
    
    nova_client.servers.list(mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(vms)
    nova_client.servers.list(mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(vms)
    auto_evacuate.acknowledge(mox.IgnoreArg(), mox.IgnoreArg())

    self.mox.ReplayAll()
    auto_evacuate.get_target_vms(nova_client)
    self.mox.VerifyAll()

  def test_get_target_vms_NG(self):
    nova_client = mox.MockAnything()
    self.mox.StubOutWithMock(nova_client, 'servers')
    self.mox.StubOutWithMock(nova_client.servers, 'list')
    self.mox.StubOutWithMock(auto_evacuate, 'acknowledge')
    vm = mox.MockAnything()
    vm.__dict__['OS-EXT-STS:vm_state']='active'
    vm.id='123456789'
    vms=[]
    
    nova_client.servers.list(mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(vms)
    nova_client.servers.list(mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(vms)
    auto_evacuate.acknowledge(mox.IgnoreArg(), mox.IgnoreArg())

    self.mox.ReplayAll()
    auto_evacuate.get_target_vms(nova_client)
    self.mox.VerifyAll()

  def test_get_destination_server_OK(self):
    self.mox.StubOutWithMock(auto_evacuate, 'broken_hostname')
    auto_evacuate.broken_hostname='dummyhost'
    nova_client = mox.MockAnything()
    self.mox.StubOutWithMock(nova_client, 'services')
    self.mox.StubOutWithMock(nova_client.services, 'list')
    self.mox.StubOutWithMock(nova_client, 'servers')
    self.mox.StubOutWithMock(nova_client.servers, 'list')
    self.mox.StubOutWithMock(auto_evacuate, 'acknowledge')
    server = mox.MockAnything()
    server.host='dummyhost'
    server.zone='zone1'
    servers=[]
    servers.append(server)
    self.mox.StubOutWithMock(auto_evacuate, 'conf')
    
    nova_client.services.list(binary='nova-compute').AndReturn(servers)
    auto_evacuate.conf['surplus_host_dict'].AndReturn({'zone1':['host01','host02','host03']})
    nova_client.servers.list(mox.IgnoreArg(), mox.IgnoreArg()).AndReturn([])
    auto_evacuate.acknowledge(mox.IgnoreArg(), mox.IgnoreArg())

    self.mox.ReplayAll()
    auto_evacuate.get_destination_server(nova_client)
    self.mox.VerifyAll()

  def test_get_destination_server_NG1(self):
    self.mox.StubOutWithMock(auto_evacuate, 'broken_hostname')
    auto_evacuate.broken_hostname='dummyhost'
    nova_client = mox.MockAnything()
    self.mox.StubOutWithMock(nova_client, 'services')
    self.mox.StubOutWithMock(nova_client.services, 'list')
    self.mox.StubOutWithMock(nova_client, 'servers')
    self.mox.StubOutWithMock(nova_client.servers, 'list')
    self.mox.StubOutWithMock(auto_evacuate, 'acknowledge')
    server = mox.MockAnything()
    server.host='dummyhost'
    server.zone='zone1'
    servers=[]
    servers.append(server)
    self.mox.StubOutWithMock(auto_evacuate, 'conf')
    
    nova_client.services.list(binary='nova-compute').AndReturn(servers)
    auto_evacuate.conf['surplus_host_dict'].AndReturn({'zone1':['host01']})
    nova_client.servers.list(mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(['dummy01', 'dummy02'])
    auto_evacuate.acknowledge(mox.IgnoreArg(), mox.IgnoreArg())

    self.mox.ReplayAll()
    auto_evacuate.get_destination_server(nova_client)
    self.mox.VerifyAll()
    
  def test_process_evacuate_OK(self):
    nova_client = mox.MockAnything()
    target_vms = []
    destination_host = 'dummy host'
    vm = mox.MockAnything()
    vm.__dict__['OS-EXT-STS:vm_state']='active'
    vm.id='123456789'
    target_vms.append(vm)

    self.mox.StubOutWithMock(auto_evacuate, 'acknowledge')
    self.mox.StubOutWithMock(nova_client, 'servers')
    self.mox.StubOutWithMock(nova_client.servers, 'evacuate')
    self.mox.StubOutWithMock(auto_evacuate, 'conf')
    auto_evacuate.conf['evacuate_with_shared_storage'].AndReturn(True)

    auto_evacuate.acknowledge(mox.IgnoreArg(), mox.IgnoreArg())
    nova_client.servers.evacuate(server=vm.id, host=destination_host, on_shared_storage=True)

    self.mox.ReplayAll()
    auto_evacuate.process_evacuate(nova_client, target_vms, destination_host)
    self.mox.VerifyAll()

  def test_process_evacuate_NG1(self):
    nova_client = mox.MockAnything()
    target_vms = []
    destination_host = 'dummy host'
    vm = mox.MockAnything()
    vm.__dict__['OS-EXT-STS:vm_state']='active'
    vm.id='123456789'
    target_vms.append(vm)

    self.mox.StubOutWithMock(auto_evacuate, 'acknowledge')
    self.mox.StubOutWithMock(nova_client, 'servers')
    self.mox.StubOutWithMock(nova_client.servers, 'evacuate')
    self.mox.StubOutWithMock(auto_evacuate, 'conf')
    auto_evacuate.conf['evacuate_with_shared_storage'].AndReturn(True)

    auto_evacuate.acknowledge(mox.IgnoreArg(), mox.IgnoreArg())
    nova_client.servers.evacuate(server=vm.id, host=destination_host, on_shared_storage=True).AndRaise(novaclient.exceptions.BadRequest('dummy exception'))
    auto_evacuate.acknowledge(mox.IgnoreArg(), mox.IgnoreArg())

    self.mox.ReplayAll()
    auto_evacuate.process_evacuate(nova_client, target_vms, destination_host)
    self.mox.VerifyAll()

  def test_process_evacuate_NG2(self):
    nova_client = mox.MockAnything()
    target_vms = []
    destination_host = 'dummy host'
    vm = mox.MockAnything()
    vm.__dict__['OS-EXT-STS:vm_state']='active'
    vm.id='123456789'
    target_vms.append(vm)

    self.mox.StubOutWithMock(auto_evacuate, 'acknowledge')
    self.mox.StubOutWithMock(nova_client, 'servers')
    self.mox.StubOutWithMock(nova_client.servers, 'evacuate')
    self.mox.StubOutWithMock(auto_evacuate, 'conf')
    auto_evacuate.conf['evacuate_with_shared_storage'].AndReturn(True)

    auto_evacuate.acknowledge(mox.IgnoreArg(), mox.IgnoreArg())
    nova_client.servers.evacuate(server=vm.id, host=destination_host, on_shared_storage=True).AndRaise(Exception('dummy exception'))
    auto_evacuate.acknowledge(mox.IgnoreArg(), mox.IgnoreArg())

    self.mox.ReplayAll()
    auto_evacuate.process_evacuate(nova_client, target_vms, destination_host)
    self.mox.VerifyAll()

  def test_is_finished_evacuate_OK(self):
    nova_client = mox.MockAnything()
    destination_host = 'dummy'
    vm = mox.MockAnything()
    vm.id='123456789'
    status = mox.MockAnything()
    status._info={'OS-EXT-SRV-ATTR:host': 'dummy', 'OS-EXT-STS:task_state': None}
    status.status = u'ACTIVE'
    self.mox.StubOutWithMock(nova_client, 'servers')
    self.mox.StubOutWithMock(nova_client.servers, 'get')
    self.mox.StubOutWithMock(auto_evacuate, 'acknowledge')

    nova_client.servers.get(server=vm.id).AndReturn(status)
    auto_evacuate.acknowledge(mox.IgnoreArg(), mox.IgnoreArg())

    self.mox.ReplayAll()
    auto_evacuate.is_finished_evacuate(nova_client, vm.id, destination_host)
    self.mox.VerifyAll()

  def test_is_finished_evacuate_OK2(self):
    nova_client = mox.MockAnything()
    destination_host = 'dummy'
    vm = mox.MockAnything()
    vm.id='123456789'
    status = mox.MockAnything()
    status._info={'OS-EXT-SRV-ATTR:host': 'dummy', 'OS-EXT-STS:task_state': None}
    status.status = u'DUMMY'
    self.mox.StubOutWithMock(nova_client, 'servers')
    self.mox.StubOutWithMock(nova_client.servers, 'get')
    self.mox.StubOutWithMock(auto_evacuate, 'acknowledge')

    nova_client.servers.get(server=vm.id).AndReturn(status)
    auto_evacuate.acknowledge(mox.IgnoreArg(), mox.IgnoreArg())

    self.mox.ReplayAll()
    auto_evacuate.is_finished_evacuate(nova_client, vm.id, destination_host)
    self.mox.VerifyAll()

  def test_check_evacuate_OK(self):
    nova_client = mox.MockAnything()
    check_vm_list = ['host01']
    destination_host = 'dummy'
    self.mox.StubOutWithMock(auto_evacuate, 'conf')
    self.mox.StubOutWithMock(time, 'time')
    self.mox.StubOutWithMock(auto_evacuate, 'acknowledge')
    self.mox.StubOutWithMock(auto_evacuate, 'is_finished_evacuate')

    time.time().AndReturn(100)
    auto_evacuate.conf['timeout'].AndReturn(300)
    auto_evacuate.conf['sleep_time'].AndReturn(0.1)
    time.time().AndReturn(200)
    auto_evacuate.acknowledge(mox.IgnoreArg(), mox.IgnoreArg())
    auto_evacuate.is_finished_evacuate(mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(True)
    auto_evacuate.acknowledge(mox.IgnoreArg(), mox.IgnoreArg())

    self.mox.ReplayAll()
    auto_evacuate.check_evacuate(nova_client, check_vm_list, destination_host)
    self.mox.VerifyAll()

  def test_check_evacuate_OK2(self):
    nova_client = mox.MockAnything()
    check_vm_list = ['host01']
    destination_host = 'dummy'
    self.mox.StubOutWithMock(auto_evacuate, 'conf')
    self.mox.StubOutWithMock(time, 'time')
    self.mox.StubOutWithMock(auto_evacuate, 'acknowledge')
    self.mox.StubOutWithMock(auto_evacuate, 'is_finished_evacuate')

    time.time().AndReturn(100)
    auto_evacuate.conf['timeout'].AndReturn(300)
    auto_evacuate.conf['sleep_time'].AndReturn(0.1)
    time.time().AndReturn(500)
    auto_evacuate.acknowledge(mox.IgnoreArg(), mox.IgnoreArg())

    self.mox.ReplayAll()
    auto_evacuate.check_evacuate(nova_client, check_vm_list, destination_host)
    self.mox.VerifyAll()

if __name__ == '__main__':
  unittest.main()

