import ConfigParser

c = ConfigParser.ConfigParser()
c.read('./sample.conf')

print c.getboolean('default', 'evacuate_with_shared_storage')
print c.get('default', 'openstack_user')
print c.get('default', 'openstack_password')
print c.get('default', 'openstack_tenant')
print c.get('default', 'openstack_auth_url')
