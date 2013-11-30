# -*- coding:utf-8 -*-
"""
@param event_id id for target event 
@param broken_hostname name for broken physical server. specify hostname with full match.
@return succes 0
        failure 1
"""

# TODO:implement logging
# TODO:error process for others

import sys
import os
from os import path
import time
import pprint
import ConfigParser
from novaclient.v1_1.client import Client
import novaclient.exceptions

event_id = '1833'
broken_hostname = 'vbox03-01'

# FIXME: modify to include own hostname. because this script may be kicked in multihost at same time.
execute_hostname = os.uname()[1]
zabbix_message_start_script = execute_hostname + ':[START]auto evacuate script start. event id:%s'
zabbix_message_finish_script = execute_hostname + ':[FINISH]auto evacuate script finish. event id:%s'

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
config.read( path.dirname( path.abspath( __file__ ) ) + '/' + 'auto_evacuate.conf')

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
def zabbixapi_acknowledge(zabbix_api, event_id, mymessage):
    if zabbix_comment_update:
        try:
            zabbix_api.event.acknowledge(eventids=event_id, message=mymessage)
        except Exception as e:
            print 'some errors occurs with zabbixapi connection'
            print e
            if not ignore_zabbix_api_connection:
                raise e

# create zabbix api object
def get_zabbix_api():
    zapi = None
    if zabbix_comment_update:
        zapi = ZabbixAPI(zabbix_url)
        try:
            zapi.login(zabbix_user, zabbix_password)
        except Exception as e:
            print 'some errors occurs'
            print e
    return zapi

# create novaclient object
def get_novaclient():
    nova_client = Client(openstack_user, openstack_password, openstack_tenant, openstack_auth_url)
    return nova_client

# get vm list on target physical server
def get_target_vms(nova_client, zapi):
    target_vms = []
    # FIXME:exclude error state vm.
    target_vms = nova_client.servers.list(True, {'all_tenants':1, 'host':broken_hostname, 'status':'ACTIVE'})
    #pprint.pprint(target_vms)

    if not target_vms:
        #pprint.pprint("no target vms.")
        zabbixapi_acknowledge(zapi, event_id, 'no targt vms on %s. nothing to do.' % broken_hostname)
    return target_vms

# get target physical server of availability zone for surplus.
def get_destination_server(nova_client):
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
            break
    #pprint.pprint(destination_host)
    return destination_host

# choose one vm
def process_evacuate(nova_client, target_vms, destination_host, zapi):
    check_vm_list = []
    for vm in target_vms:
        try:
            # update trigger comment on zabbix
            zabbixapi_acknowledge(zapi, event_id, "try to evacuate vm(%s) from %s to %s" % (vm.id, broken_hostname, destination_host['hostname']) )
            # run evacuate
            nova_client.servers.evacuate(server=vm.id, host=destination_host['hostname'], on_shared_storage=evacuate_with_shared_storage)
            check_vm_list.append(vm.id)
        except novaclient.exceptions.BadRequest as e:
            #pprint.pprint(e)
            #print e
            #print e.http_status
            zabbixapi_acknowledge(zapi, event_id, "error occurs on evacuate vm. UUID:%s\n%s" % (vm.id, e))
        except Exception as e:
            zabbixapi_acknowledge(zapi, event_id, "error occurs on evacuate vm. UUID:%s\n%s" % (vm.id, e))
    return check_vm_list

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
# check completion for evacuate vms.
def check_evacuate(nova_client, check_vm_list, destination_host, zapi):
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
                zabbixapi_acknowledge(zapi, event_id, "finish evacuate vm(%s)" % vm_id )
        # wait 0.5 sec
        time.sleep(0.5)


def main():
    result = 0
    try:
        # FIXME: check duplicate process

        # create zabbix api object
        zapi = get_zabbix_api()

        # update trigger comment on zabbix
        zabbixapi_acknowledge(zapi, event_id, zabbix_message_start_script % event_id)

        # create novaclient object
        novaclient = get_novaclient()

        # get vm list on target physical server
        target_vms = get_target_vms(novaclient, zapi)

        if target_vms:
            # get target physical server of availability zone for surplus.
            destination_host = get_destination_server(novaclient)
                
            # process evacuate
            check_vm_list = process_evacuate(novaclient, target_vms, destination_host, zapi)

            # check completion for evacuate vms.
            check_evacuate(novaclient, check_vm_list, destination_host, zapi)

    except Exception as e:
        zabbixapi_acknowledge(zapi, event_id, str(e))
        result = 1
    finally:
        # update trigger comment on zabbix
        zabbixapi_acknowledge(zapi, event_id, zabbix_message_finish_script % event_id)
        
        # finish with exit code.
        sys.exit(result)

if __name__ == '__main__':
    main()

