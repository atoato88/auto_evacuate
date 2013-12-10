# -*- coding:utf-8 -*-
"""
@param event_id id for target event 
@param broken_hostname name for broken physical server. specify hostname with full match.
@return success 0
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
import syslog

event_id = ''
broken_hostname = ''
conf={}

# FIXME: modify to include own hostname. because this script may be kicked in multihost at same time.
execute_hostname = os.uname()[1]
zabbix_message_start_script = execute_hostname + ':[START]auto evacuate script start. event id:%s'
zabbix_message_finish_script = execute_hostname + ':[FINISH]auto evacuate script finish. event id:%s'

def parse_args():
    global event_id
    global broken_hostname
    argvs = sys.argv
    argc = len(argvs)
    #print argvs
    #print argc

    if argc == 3:
        event_id = argvs[1]
        broken_hostname = argvs[2]
    else:
        print 'usage: <command> <event_id on zabbix> <broken physical hostname>'
        sys.exit(1)

def load_config():
    # load settings
    global conf
    config = ConfigParser.ConfigParser()
    config.read( path.dirname( path.abspath( __file__ ) ) + '/' + 'auto_evacuate.conf')

    conf['openstack_user'] = config.get('DEFAULT', 'openstack_user')
    conf['openstack_password'] = config.get('DEFAULT', 'openstack_password')
    conf['openstack_tenant'] = config.get('DEFAULT', 'openstack_tenant')
    conf['openstack_auth_url'] = config.get('DEFAULT', 'openstack_auth_url')
    conf['surplus_availability_zone_name'] = config.get('DEFAULT', 'surplus_availability_zone_name')
    conf['evacuate_with_shared_storage'] = config.getboolean('DEFAULT', 'evacuate_with_shared_storage')
    # FIXME: below param is unused.
    conf['retry_count'] = config.getint('DEFAULT', 'retry_count')
    conf['timeout'] = config.getint('DEFAULT', 'timeout')
    # FIXME: below param is unused.
    conf['concurrent_evacuate_count'] = config.getint('DEFAULT', 'concurrent_evacuate_count')

    conf['zabbix_user'] = config.get('DEFAULT', 'zabbix_user')
    conf['zabbix_password'] = config.get('DEFAULT', 'zabbix_password')
    conf['zabbix_url'] = config.get('DEFAULT', 'zabbix_url')
    conf['zabbix_comment_update'] = config.getboolean('DEFAULT', 'zabbix_comment_update')
    conf['ignore_zabbix_api_connection'] = config.getboolean('DEFAULT', 'ignore_zabbix_api_connection')

    # FIXME: below param is unused.
    conf['wait_duplicate_process'] = config.getboolean('DEFAULT', 'wait_duplicate_process')
    
    if conf['zabbix_comment_update']:
        # create zabbix api object
        conf['zapi'] = get_zabbix_api()

    return conf

"""
update comment on event specified by event_id
@param zabbix_api zabbix api object
@param event_id id for target event 
@param message messega for update
"""
def acknowledge(event_id, mymessage):
    syslog.syslog(syslog.LOG_INFO, mymessage)
    if not conf['zabbix_comment_update']:
        return
    zabbix_comment_update=conf['zabbix_comment_update']
    ignore_zabbix_api_connection=conf['ignore_zabbix_api_connection']
    if zabbix_comment_update:
        try:
            conf['zapi'].event.acknowledge(eventids=event_id, message=mymessage[:255] if len(mymessage) > 255 else mymessage)
        except Exception as e:
            syslog.syslog(syslog.LOG_ERR, 'some errors occurs with zabbixapi connection')
            syslog.syslog(syslog.LOG_ERR, str(e))
            if not ignore_zabbix_api_connection:
                raise e

# create zabbix api object
def get_zabbix_api():
    from pyzabbix import ZabbixAPI
    zabbix_comment_update=conf['zabbix_comment_update']
    zapi = None
    if zabbix_comment_update:
        zapi = ZabbixAPI(conf['zabbix_url'])
        try:
            zapi.login(conf['zabbix_user'], conf['zabbix_password'])
        except Exception as e:
            syslog.syslog(syslog.LOG_ERR, 'some errors occurs')
            syslog.syslog(syslog.LOG_ERR, str(e))
    return zapi

# create novaclient object
def get_novaclient():
    nova_client = Client(conf['openstack_user'], conf['openstack_password'], conf['openstack_tenant'], conf['openstack_auth_url'])
    return nova_client

# get vm list on target physical server
def get_target_vms(nova_client):
    target_vms = []
    # FIXME:exclude error state vm.
    target_vms = nova_client.servers.list(True, {'all_tenants':1, 'host':broken_hostname, 'status':'ACTIVE'})

    if not target_vms:
        acknowledge(event_id, 'no target vms on %s. nothing to do.' % broken_hostname)
    return target_vms

# get target physical server of availability zone for surplus.
def get_destination_server(nova_client):
    availability_zone_list = nova_client.availability_zones.list()

    # FIXME: refactor into more efficient search logic.
    for e in availability_zone_list:
        if e.zoneName == conf['surplus_availability_zone_name']:
            target_availability_zone = e

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
    return destination_host

# choose one vm
def process_evacuate(nova_client, target_vms, destination_host):
    check_vm_list = []
    for vm in target_vms:
        try:
            # update trigger comment on zabbix
            acknowledge(event_id, "try to evacuate vm(%s) from %s to %s" % (vm.id, broken_hostname, destination_host['hostname']) )
            # run evacuate
            nova_client.servers.evacuate(server=vm.id, host=destination_host['hostname'], on_shared_storage=conf['evacuate_with_shared_storage'])
            check_vm_list.append(vm.id)
        except novaclient.exceptions.BadRequest as e:
            #pprint.pprint(e)
            #print e
            #print e.http_status
            acknowledge(event_id, "error occurs on evacuate vm. UUID:%s\n%s" % (vm.id, e))
        except Exception as e:
            acknowledge(event_id, "error occurs on evacuate vm. UUID:%s\n%s" % (vm.id, e))
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
def check_evacuate(nova_client, check_vm_list, destination_host):
    start_time = time.time()
    timeout = conf['timeout']
    while True:
        if len(check_vm_list) == 0:
            break
        if time.time() - start_time > timeout:
            break
        for vm_id in check_vm_list:
            if is_finished_evacuate(nova_client, vm_id, destination_host['hostname']):
                check_vm_list.remove(vm_id)
                # update trigger comment on zabbix
                acknowledge(event_id, "finish evacuate vm(%s)" % vm_id )
        # wait 0.5 sec
        time.sleep(0.5)

def main():
    syslog.openlog('auto_evacuate', syslog.LOG_PID, syslog.LOG_SYSLOG)
    parse_args()
    load_config()
    result = 0
    try:
        # FIXME: check duplicate process

        # update event comment on zabbix
        acknowledge(event_id, zabbix_message_start_script % event_id)

        # create novaclient object
        novaclient = get_novaclient()

        # get vm list on target physical server
        target_vms = get_target_vms(novaclient)

        if target_vms:
            # get target physical server of availability zone for surplus.
            destination_host = get_destination_server(novaclient)
                
            # process evacuate
            check_vm_list = process_evacuate(novaclient, target_vms, destination_host)

            # check completion for evacuate vms.
            check_evacuate(novaclient, check_vm_list, destination_host)

    except Exception as e:
        acknowledge(event_id, str(e))
        result = 1
    finally:
        # update event comment on zabbix
        acknowledge(event_id, zabbix_message_finish_script % event_id)

        syslog.closelog()
        
        # finish with exit code.
        sys.exit(result)

if __name__ == '__main__':
    main()

