# -*- coding:utf-8 -*-

# TODO:implement logging
# TODO:error process for others

import sys
import time
import pprint
import ConfigParser
from novaclient.v1_1.client import Client
import novaclient.exceptions

"""
@param event_id id for target event 
@param broken_hostname name for broken physical server. specify hostname with full match.
@return succes 0
        failure 1
"""

event_id = '1833'
broken_hostname = 'vbox03-01'

zabbix_message_start_script = '[START]auto evacuate script start. event id:%s'
zabbix_message_finish_script = '[FINISH]auto evacuate script finish. event id:%s'

argvs = sys.argv
argc = len(argvs)
print argvs
print argc

if argc == 3:
    event_id = argvs[1]
    broken_hostname = argvs[2]
else:
    print 'usage: <command> <event_id on zabbix> <broken physical hostname>'
    sys.exit(1)

# ---------------------------------------------------------------------------------------
# load settings
config = ConfigParser.ConfigParser()
config.read('/home/ubuntu/auto_evacuate/auto_evacuate.conf')

openstack_user = config.get('DEFAULT', 'openstack_user')
openstack_password = config.get('DEFAULT', 'openstack_password')
openstack_tenant = config.get('DEFAULT', 'openstack_tenant')
openstack_auth_url = config.get('DEFAULT', 'openstack_auth_url')
surplus_availability_zone_name = config.get('DEFAULT', 'surplus_availability_zone_name')
evacuate_with_shared_storage = config.getboolean('DEFAULT', 'evacuate_with_shared_storage')
# FIXME: below param is unused.
retry_count = config.getint('DEFAULT', 'retry_count')
timeout = config.getint('DEFAULT', 'timeout')
# FIXME: below param is unused.
concurrent_evacuate_count = config.getint('DEFAULT', 'concurrent_evacuate_count')

zabbix_user = config.get('DEFAULT', 'zabbix_user')
zabbix_password = config.get('DEFAULT', 'zabbix_password')
zabbix_url = config.get('DEFAULT', 'zabbix_url')
zabbix_comment_update = config.getboolean('DEFAULT', 'zabbix_comment_update')
ignore_zabbix_api_connection = config.getboolean('DEFAULT', 'ignore_zabbix_api_connection')

# FIXME: below param is unused.
wait_duplicate_process = config.getboolean('DEFAULT', 'wait_duplicate_process')
# ---------------------------------------------------------------------------------------

if zabbix_comment_update:
    from pyzabbix import ZabbixAPI

"""
update comment on event specified by event_id
@param zabbix_api zabbix api object
@param event_id id for target event 
@param message messega for update
"""
def zabbixapi_ackknowledge(zabbix_api, event_id, mymessage):
    try:
        zabbix_api.event.acknowledge(eventids=event_id, message=mymessage)
    except Exception as e:
        print 'some errors occurs with zabbixapi connection'
        print e
        if not ignore_zabbix_api_connection:
            raise e

# FIXME: check duplicate process


# create zabbix api object
if zabbix_comment_update:
    zapi = ZabbixAPI(zabbix_url)
    try:
        zapi.login(zabbix_user, zabbix_password)
    except Exception as e:
        print 'some errors occurs'
        print e

# update trigger comment on zabbix
#if zabbix_comment_update:
#    target_trigger = zapi.trigger.get(triggerids=['13595'],
#                                      output='extend',
#                                      expandDescription=1,
#                                      expandData='host'
#                                      )[0]
#    pprint.pprint(target_trigger)
#    target_event = zapi.event.get(acknowledged=1,
#                                  output='extend',
#                                  select_acknowledges='extend'
#                                  )

# update trigger comment on zabbix
if zabbix_comment_update:
    zabbixapi_ackknowledge(zapi, event_id, zabbix_message_start_script % event_id)

# create novaclient object
nova_client = Client(openstack_user, openstack_password, openstack_tenant, openstack_auth_url)

# get vm list on target physical server
target_vms = nova_client.servers.list(True, {'all_tenants':1, 'host':broken_hostname})
#pprint.pprint(target_vms)

if not target_vms:
    pprint.pprint("no target vms.")
    if zabbix_comment_update:
        zabbixapi_ackknowledge(zapi, event_id, 'no targt vms. nothing to do.')
    sys.exit(0)

# get target physical server of availability zone for surplus.
availability_zone_list = nova_client.availability_zones.list()

# FIXME: refactor into more efficient search logic.
for e in availability_zone_list:
    if e.zoneName == surplus_availability_zone_name:
        target_availability_zone = e
#pprint.pprint(target_availability_zone)

def is_valid_destination_host(client, hostname):
    if len(client.servers.list(True, {'all_tenants':1, 'host':hostname})) == 0:
        return True
    else:
        return False

# check vm-space on target physical server
hosts = target_availability_zone.hosts
for h in hosts:
    if is_valid_destination_host(nova_client, h):
        destination_host = hosts[h]
        destination_host['hostname'] = h
#pprint.pprint(destination_host)

# choose one vm
check_vm_list = []
for vm in target_vms:
    try:
        # update trigger comment on zabbix
        if zabbix_comment_update:
            zabbixapi_ackknowledge(zapi, event_id, "try to evacuate vm(%s) to %s" % (vm.id, destination_host['hostname']) )
        # run evacuate
        nova_client.servers.evacuate(server=vm.id, host=destination_host['hostname'], on_shared_storage=evacuate_with_shared_storage)
        check_vm_list.append(vm.id)
    except novaclient.exceptions.BadRequest as e:
        #pprint.pprint(e)
        #print e
        #print e.http_status
        if zabbix_comment_update:
            zabbixapi_ackknowledge(zapi, event_id, "error occurs on evacuate vm. UUID:%s\n%s" % (vm.id, e))

# check result for evacuate with loop 
def is_finished_evacuate(client, vm_id, destination_hostname):
    s = client.servers.get(server=vm_id)
    if (s._info['OS-EXT-SRV-ATTR:host'] == destination_hostname) and \
        (s.status == u'ACTIVE') and \
        (s._info['OS-EXT-STS:task_state'] == None):
        return True
    else:
        return False

# FIXME: possibility for infinite loop
start_time = time.time()
while True:
    if len(check_vm_list) == 0:
        break
    if time.time() - start_time > timeout:
        break
    for vm_id in check_vm_list:
        if is_finished_evacuate(nova_client, vm_id, destination_host['hostname']):
            check_vm_list.remove(vm_id)
            # update trigger comment on zabbix
            if zabbix_comment_update:
                zabbixapi_ackknowledge(zapi, event_id, "finish evacuate vm(%s)" % vm_id )
    # wait 0.5 sec
    time.sleep(0.5)

# update trigger comment on zabbix
if zabbix_comment_update:
    zabbixapi_ackknowledge(zapi, event_id, zabbix_message_finish_script % event_id)

# finish with success code.
sys.exit(0)
