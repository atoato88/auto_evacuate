# -*- coding:utf-8 -*-
"""
@param event_id id for target event on zabbix
@param broken_hostname name for broken physical server. specify hostname with full match.
@return success 0
        failure 1
"""

import sys
import os
from os import path
import time
import ConfigParser
from novaclient.v1_1.client import Client
import novaclient.exceptions
import syslog
import optparse
import traceback

event_id = ''
broken_hostname = ''
conf={}

# include own hostname. because this script may be kicked in multihost at same time.
execute_hostname = os.uname()[1]
zabbix_message_start_script = execute_hostname + ':[START]auto evacuate script start. event id:%s'
zabbix_message_finish_script = execute_hostname + ':[FINISH]auto evacuate script finish. event id:%s'

def parse_args():
    help_str = 'usage: <command> <event_id on zabbix> <broken physical hostname> [--dry-run]\n if --dry-run present, don\'t process evacuate. check only.'
    parser = optparse.OptionParser()
    parser.add_option('--dry-run', action="store_true", default=False)

    (options, args) = parser.parse_args()

    global event_id
    global broken_hostname
    global dry_run
    dry_run = options.dry_run

    if len(args) == 2:
        event_id = args[0]
        broken_hostname = args[1]
    else:
        print help_str
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
    conf['surplus_host_dict'] = config._sections['surplus_host']
    for item in conf['surplus_host_dict'].items():
        conf['surplus_host_dict'][item[0]] = [ i.strip() for i in item[1].split(',') if len(i.strip()) != 0 ]
    
    conf['evacuate_with_shared_storage'] = config.getboolean('DEFAULT', 'evacuate_with_shared_storage')
    conf['timeout'] = config.getint('DEFAULT', 'timeout')
    conf['sleep_time'] = config.getfloat('DEFAULT', 'sleep_time')

    conf['zabbix_user'] = config.get('DEFAULT', 'zabbix_user')
    conf['zabbix_password'] = config.get('DEFAULT', 'zabbix_password')
    conf['zabbix_url'] = config.get('DEFAULT', 'zabbix_url')
    conf['zabbix_comment_update'] = config.getboolean('DEFAULT', 'zabbix_comment_update')
    conf['ignore_zabbix_api_connection'] = config.getboolean('DEFAULT', 'ignore_zabbix_api_connection')
    
    if conf['zabbix_comment_update']:
        # create zabbix api object
        conf['zapi'] = get_zabbix_api()

    return conf

"""
insert log to syslog.
update comment on event specified by event_id.
@param event_id id for target event 
@param message messeage for update
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
            syslog.syslog(syslog.LOG_ERR, '[ERROR]some errors occurs with zabbixapi connection')
            syslog.syslog(syslog.LOG_ERR, '[ERROR]'+str(e))
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
            syslog.syslog(syslog.LOG_ERR, '[ERROR]some errors occurs')
            syslog.syslog(syslog.LOG_ERR, '[ERROR]'+str(e))
    return zapi

# create novaclient object
def get_novaclient():
    nova_client = Client(conf['openstack_user'], conf['openstack_password'], conf['openstack_tenant'], conf['openstack_auth_url'])
    return nova_client

# get vm list on target physical server
def get_target_vms(nova_client):
    target_vms = []
    #target_vms = nova_client.servers.list(True, {'all_tenants':1, 'host':broken_hostname, 'status':'ACTIVE'})
    #nova_client.servers.list(True, {'all_tenants':1, 'host':broken_hostname, 'status':'SHUTOFF'})

    vms = nova_client.servers.list(True, {'all_tenants':1, 'host':broken_hostname})
    for vm in vms:
        if vm.__dict__['OS-EXT-STS:vm_state'] in ['active', 'stopped']:
            target_vms.append(vm)

    # or should use vm-extension status?
    for vm in target_vms:
        acknowledge(event_id, 'target vm:%s' % vm.id )

    if not target_vms:
        acknowledge(event_id, 'no target vms on %s. nothing to do.' % broken_hostname)
    return target_vms

# get target physical server for surplus.
def get_destination_server(nova_client):
    destination_hosts = []
    destination_host = None

    broken_nova_compute = None
    #nova_servers = nova_client.services.list(binary='nova-compute')
    for server in nova_client.services.list(binary='nova-compute'):
        if server.host == broken_hostname:
            broken_nova_compute = server
            destination_hosts = conf['surplus_host_dict'][broken_nova_compute.zone]
            break

    def is_valid_destination_host(client, hostname):
        if len(client.servers.list(True, {'all_tenants':1, 'host':hostname})) == 0:
            return True
        else:
            return False

    # check vm-space on target physical server
    for h in destination_hosts:
        if is_valid_destination_host(nova_client, h):
            destination_host = h
            acknowledge(event_id, 'destination physical server:%s' % h )
            break
    if not destination_host:
        acknowledge(event_id, 'no destination physical server exists.')
    return destination_host

# evacuate vm
def process_evacuate(nova_client, target_vms, destination_host):
    check_vm_list = []
    for vm in target_vms:
        try:
            # update trigger comment on zabbix
            acknowledge(event_id, "try to evacuate vm(%s) from %s to %s" % (vm.id, broken_hostname, destination_host) )
            # run evacuate
            nova_client.servers.evacuate(server=vm.id, host=destination_host, on_shared_storage=conf['evacuate_with_shared_storage'])
            check_vm_list.append(vm.id)
        except novaclient.exceptions.BadRequest as e:
            acknowledge(event_id, "error occurs on evacuate vm. UUID:%s\n%s" % (vm.id, traceback.format_exc()))
        except Exception as e:
            acknowledge(event_id, "error occurs on evacuate vm. UUID:%s\n%s" % (vm.id, traceback.format_exc()))
    return check_vm_list

# check result for evacuate with loop 
def is_finished_evacuate(client, vm_id, destination_hostname):
    s = client.servers.get(server=vm_id)
    acknowledge(event_id, "vm_id:%s, host:%s, status:%s, task_state:%s" % 
                          (str(vm_id), s._info['OS-EXT-SRV-ATTR:host'], 
                            s.status, 
                            s._info['OS-EXT-STS:task_state'] ) 
                )
    if (s._info['OS-EXT-SRV-ATTR:host'] == destination_hostname) and \
        (s.status in [u'ACTIVE', u'SHUTOFF']) and \
        (s._info['OS-EXT-STS:task_state'] == None):
        return True
    else:
        return False

# check completion for evacuated vms.
def check_evacuate(nova_client, check_vm_list, destination_host):
    start_time = time.time()
    timeout = conf['timeout']
    sleep_time = conf['sleep_time']
    while True:
        if len(check_vm_list) == 0:
            break
        if time.time() - start_time > timeout:
            acknowledge(event_id, "timeout for checking evacuate status." )
            break
        for vm_id in check_vm_list:
            acknowledge(event_id, "check for status vm(%s)" % vm_id )
            if is_finished_evacuate(nova_client, vm_id, destination_host):
                check_vm_list.remove(vm_id)
                # update log
                acknowledge(event_id, "finish evacuate vm(%s)" % vm_id )
        # wait
        time.sleep(sleep_time)

def main():
    syslog.openlog('auto_evacuate', syslog.LOG_PID, syslog.LOG_SYSLOG)
    parse_args()
    load_config()
    result = 0
    try:
        # FIXME: check duplicate process

        # update event comment on zabbix
        acknowledge(event_id, zabbix_message_start_script % event_id)
        acknowledge(event_id, "broken_hostname:%s"  % broken_hostname)
        if dry_run:
            acknowledge(event_id, "DRY RUN MODE")

        # create novaclient object
        novaclient = get_novaclient()

        # get vm list on target physical server
        target_vms = get_target_vms(novaclient)
        
        # get target physical server for surplus.
        destination_host = get_destination_server(novaclient)

        if target_vms and destination_host and not dry_run:
            # process evacuate
            check_vm_list = process_evacuate(novaclient, target_vms, destination_host)

            # check completion for evacuate vms.
            check_evacuate(novaclient, check_vm_list, destination_host)

    except Exception as e:
        acknowledge(event_id, traceback.format_exc())
        result = 1
    finally:
        # update event comment on zabbix
        acknowledge(event_id, zabbix_message_finish_script % event_id)

        syslog.closelog()
        
        # finish with exit code.
        sys.exit(result)

if __name__ == '__main__':
    main()

