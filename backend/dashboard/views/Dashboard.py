"""
you don't find what you looking for,
    when you're looking.
"""
import json
import os
import time

from backend.messages import mt
from backend.services.zabbix_service.zabbix_packages import ZabbixHelper
from backend.utils import create_response, permission_for_view
from django.conf import settings
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.views import APIView
from settings.models import UserSystem
from settings.permissions import IsDetailAvailable, IsAuthenticated

from ..configs.schema import validate_json_config
from ..utils import statuses_calculator as sc
from ..utils.utils import humanize_bytes


class DashboardView(APIView):
    permission_classes = [IsAuthenticated, permission_for_view("DASHBOARD"), IsDetailAvailable]

    @swagger_auto_schema(
        operation_summary="Get system metrics like CPU, RAM, Disk, and Network",
        operation_description="Fetches metrics data for CPU, RAM, Disk, and Network interfaces from Zabbix.",
        responses={
            200: openapi.Response(
                description="System metrics response",
                examples={
                    "application/json": {
                        "success": True,
                        "message": "success",
                        "data": {
                            "CPU": {
                                "description": "Average CPU load over the last 15 minutes",
                                "last_value": "1.898438",
                                "pre_value": "1.971191",
                                "lastclock": "2024-10-19 19:56:19"
                            },
                            "RAM": {
                                "description": "Available RAM in bytes",
                                "last_value": "1295781888",
                                "pre_value": "1513422848",
                                "lastclock": "2024-10-19 19:57:03"
                            },
                            "Disk": {
                                "description": "Total disk size in bytes for the root (/) partition",
                                "last_value": "83955703808",
                                "pre_value": "83955703808",
                                "lastclock": "2024-10-19 19:56:56"
                            },
                            "Network": {
                                "description": "Incoming traffic on the network interface",
                                "last_value": "0",
                                "pre_value": "0",
                                "lastclock": "1970-01-01 00:00:00"
                            }
                        }
                    }
                }
            ),
            500: openapi.Response(
                description="Internal Server Error",
                examples={
                    "application/json": {
                        "success": False,
                        "message": "The Reason of the Error",
                    }
                }
            )
        }
    )
    def get(self, request):
        try:
            user_system = request.user.usersystem
            zabbix_details = user_system.zabbix_details

            zabbix_helper = ZabbixHelper(
                url=zabbix_details['url'],
                user=zabbix_details['username'],
                password=zabbix_details['password'],
                host_name=zabbix_details['host_name']
            )

            # Fetch General Metric
            cpu = zabbix_helper.get_item_data('system.cpu.load[all,avg15]')
            ram = zabbix_helper.get_item_data('vm.memory.size[available]')
            disk = zabbix_helper.get_item_data('vfs.fs.size[/,total]')

            data = {
                'CPU': {
                    'description': 'Average CPU load over the last 15 minutes',
                    'last_value': cpu[0].get('lastvalue', None),
                    'pre_value': cpu[0].get('prevvalue', None),
                    'lastclock': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(cpu[0].get('lastclock', None)))),
                },
                'RAM': {
                    'description': 'Available RAM in bytes',
                    'last_value': ram[0].get('lastvalue', None),
                    'pre_value': ram[0].get('prevvalue', None),
                    'lastclock': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(ram[0].get('lastclock', None)))),
                },
                'Disk': {
                    'description': 'Total disk size in bytes for the root (/) partition',
                    'last_value': disk[0].get('lastvalue', None),
                    'pre_value': disk[0].get('prevvalue', None),
                    'lastclock': time.strftime('%Y-%m-%d %H:%M:%S',
                                               time.localtime(int(disk[0].get('lastclock', None)))),
                }
            }
            return create_response(success=True, status=status.HTTP_200_OK, data=data, message=mt[200])
        except ValueError as e:
            return create_response(success=False, status=status.HTTP_500_INTERNAL_SERVER_ERROR, message=str(e))


class SystemDetailView(APIView):
    permission_classes = [IsAuthenticated, IsDetailAvailable]

    STATUS_FUNCTIONS = {}
    bytes_data = []
    config_file = ''
    general_items = []
    metric_items = []
    date_data = []

    def load_config(self, configfile):
        config_path = os.path.join(settings.BASE_DIR, 'dashboard', f'configs/{configfile}')

        with open(config_path, 'r') as file:
            config_data = json.load(file)

        if not validate_json_config(config_data):
            raise ValueError(f"Invalid JSON format in {configfile}")

        return config_data

    def get_status(self, item_key, last_value, normal_value, warning_value):
        if item_key in self.STATUS_FUNCTIONS:
            status_function = self.STATUS_FUNCTIONS[item_key]
            return status_function(last_value, normal_value, warning_value)
        else:
            raise ValueError(f"No status function defined for {item_key}")

    def fetch_and_format_history(self, item, item_config, config, metric_items):
        zabbix_helper = ZabbixHelper()
        history_data = zabbix_helper.get_item_history(item)

        formatted_history = []
        for entry in history_data:
            clock = entry['clock']
            value = entry['value']

            formatted_entry = {
                'clock': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(clock))),
                'value': value,
            }
            if item in metric_items:
                formatted_entry['status'] = self.get_status(item_config, float(value),
                                                            config[item_config]['value']['normal'],
                                                            config[item_config]['value']['warning'])

            formatted_history.append(formatted_entry)
        return formatted_history

    def get_data(self, general_items, metric_items, config, user_system):
        zabbix_helper = ZabbixHelper(url=user_system.zabbix_details['url'],
                                     user=user_system.zabbix_details['username'],
                                     password=user_system.zabbix_details['password'],
                                     host_name=user_system.zabbix_details['host_name']
                                     )

        general_data = {item: zabbix_helper.get_item_data(item) for item in general_items}
        metric_data = {item: zabbix_helper.get_item_data(item) for item in metric_items}

        data = []

        # Process general items
        for item, item_info in general_data.items():
            value = item_info[0].get('lastvalue', 0)
            if item in self.bytes_data:
                value = humanize_bytes(value)
            elif item in self.date_data:
                value = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(value)))

            if item.split(".")[1] in ['dev']:
                item_config = '.'.join(item.split('[')[:-1])
            elif item.split(".")[1] in ['if']:
                base_item = item.split("[")[0]
                inner_content = item[item.index("[") + 1:item.index("]")]
                inner_parts = inner_content.split(",")

                if len(inner_parts) == 1:
                    item_config = base_item
                else:
                    item_config = base_item + "." + inner_parts[1].strip()
            else:
                item_config = item

            data.append({
                'name': config[item_config]['name'],
                'description': config[item_config]['description'],
                'value': value,
                'history': self.fetch_and_format_history(item, item_config, config, metric_items),
            })

        # Process metric items
        for item, item_info in metric_data.items():
            print(item_info[0], 1212121)
            last_value = float(item_info[0]['lastvalue'])

            if item.split(".")[1] in ['dev']:
                item_config = '.'.join(item.split('[')[:-1])
            elif item.split(".")[1] in ['if']:
                base_item = item.split("[")[0]
                inner_content = item[item.index("[") + 1:item.index("]")]
                inner_parts = inner_content.split(",")

                if len(inner_parts) == 1:
                    item_config = base_item
                else:
                    item_config = base_item + "." + inner_parts[1].strip()
            else:
                item_config = item

            item_status = self.get_status(item_config, last_value, config[item_config]['value']['normal'],
                                          config[item_config]['value']['warning'])

            data.append({
                'name': config[item_config]['name'],
                'description': config[item_config]['description'],
                'value': last_value,
                'status': item_status,
                'recommendation': config[item_config]['recommendations'][item_status],
                'history': self.fetch_and_format_history(item, item_config, config, metric_items),
            })

        return data

    @swagger_auto_schema(
        operation_summary="Get detailed system metric",
        operation_description="Fetches a detailed view of specific system metrics (e.g., CPU, RAM, Disk, Network) from Zabbix, including their status, history, and recommendations.",
        responses={
            200: openapi.Response(
                description="System metric detailed response",
                examples={
                    "application/json": {
                        "success": True,
                        "message": "success",
                        "data": {
                            "General Item Name": {
                                "description": "General item Description",
                                "value": "000",
                                "history": []
                            },
                            "Metric Item Name": {
                                "description": "Metric Item Description",
                                "value": 1.476074,
                                "status": "normal",
                                "recommendation": "",
                                "history": [
                                    {
                                        "clock": "2024-10-19 20:08:19",
                                        "value": "1.476074",
                                        "status": "normal"
                                    },
                                    {
                                        "clock": "2024-10-19 20:07:19",
                                        "value": "1.526367",
                                        "status": "normal"
                                    }
                                ]
                            }
                        }
                    }
                }
            ),
            500: openapi.Response(
                description="Internal Server Error",
                examples={
                    "application/json": {
                        "success": False,
                        "message": "The Reason of the Error",
                    }
                }
            )
        }
    )
    def get(self, request):
        user = request.user
        user_system = UserSystem.objects.get(user=user)
        if not user_system:
            return create_response(success=False, status=status.HTTP_401_UNAUTHORIZED, message=mt[403])
        try:
            config = self.load_config(self.config_file)
            data = self.get_data(self.general_items, self.metric_items, config, user_system)
            return create_response(success=True, data=data, status=status.HTTP_200_OK, message=mt[200])
        except ValueError as e:
            return create_response(success=False, status=status.HTTP_500_INTERNAL_SERVER_ERROR, message=str(e))


class CPUDetailView(SystemDetailView):
    permission_classes = [IsAuthenticated, permission_for_view('CPU'), IsDetailAvailable]

    STATUS_FUNCTIONS = {
        'system.cpu.load[all,avg15]': sc.status_per_core,
        'system.cpu.load[all,avg5]': sc.status_per_core,
        'system.cpu.load[all,avg1]': sc.status_per_core,
        'system.cpu.switches': sc.status_per_core,
        'system.cpu.intr': sc.status_per_core,
        'system.cpu.util[,guest_nice]': sc.main_status,
        'system.cpu.util[,guest]': sc.main_status,
        'system.cpu.util[,idle]': sc.main_status_reverse,
        'system.cpu.util[,interrupt]': sc.main_status,
        'system.cpu.util[,iowait]': sc.main_status,
        'system.cpu.util[,nice]': sc.main_status,
        'system.cpu.util[,softirq]': sc.main_status,
        'system.cpu.util[,steal]': sc.main_status,
        'system.cpu.util[,system]': sc.main_status,
        'system.cpu.util[,user]': sc.main_status,
        'system.cpu.util': sc.main_status
    }

    config_file = 'cpu_config.json'
    general_items = ['system.cpu.num']
    metric_items = [
        'system.cpu.load[all,avg15]',
        'system.cpu.load[all,avg5]',
        'system.cpu.load[all,avg1]',
        'system.cpu.switches',
        'system.cpu.intr',
        'system.cpu.util[,guest_nice]',
        'system.cpu.util[,guest]',
        'system.cpu.util[,idle]',
        'system.cpu.util[,interrupt]',
        'system.cpu.util[,iowait]',
        'system.cpu.util[,nice]',
        'system.cpu.util[,softirq]',
        'system.cpu.util[,steal]',
        'system.cpu.util[,system]',
        'system.cpu.util[,user]',
        'system.cpu.util'
    ]


class RamDetailView(SystemDetailView):
    permission_classes = [IsAuthenticated, permission_for_view('RAM'), IsDetailAvailable]

    STATUS_FUNCTIONS = {
        'vm.memory.size[pavailable]': sc.main_status_reverse,
        'vm.memory.utilization': sc.main_status,
        'system.swap.size[,pfree]': sc.main_status_reverse,
    }

    config_file = 'ram_config.json'

    general_items = [
        'vm.memory.size[available]',
        'vm.memory.size[total]',
        'system.swap.size[,free]',
        'system.swap.size[,total]',
    ]
    metric_items = [
        'vm.memory.size[pavailable]',
        'vm.memory.utilization',
        'system.swap.size[,pfree]'
    ]

    bytes_data = [
        'vm.memory.size[available]',
        'vm.memory.size[total]'
    ]


class FileSystemDetailView(SystemDetailView):
    permission_classes = [IsAuthenticated, permission_for_view('FS'), IsDetailAvailable]

    STATUS_FUNCTIONS = {
        "vfs.fs.inode[/,pfree]": sc.main_status_reverse,
        "vfs.fs.size[/,pused]": sc.main_status,
        "vfs.fs.inode[/boot,pfree]": sc.main_status_reverse,
        "vfs.fs.size[/boot,pused]": sc.main_status,
        "vfs.fs.inode[/home,pfree]": sc.main_status_reverse,
        "vfs.fs.size[/home,pused]": sc.main_status,
    }

    config_file = 'filesystem_config.json'

    general_items = [
        'vfs.fs.size[/,total]',
        'vfs.fs.size[/,used]',
        'vfs.fs.size[/boot,total]',
        'vfs.fs.size[/boot,used]',
        'vfs.fs.size[/home,total]',
        'vfs.fs.size[/home,used]'

    ]

    metric_items = [
        'vfs.fs.inode[/,pfree]',
        'vfs.fs.size[/,pused]',
        'vfs.fs.inode[/boot,pfree]',
        'vfs.fs.size[/boot,pused]',
        'vfs.fs.inode[/home,pfree]',
        'vfs.fs.size[/home,pused]'
    ]

    bytes_data = [
        'vfs.fs.size[/,total]',
        'vfs.fs.size[/,used]',
        'vfs.fs.size[/boot,total]',
        'vfs.fs.size[/boot,used]',
        'vfs.fs.size[/home,total]',
        'vfs.fs.size[/home,used]'

    ]


class GeneralDetailView(SystemDetailView):
    permission_classes = [IsAuthenticated, permission_for_view('GENERAL'), IsDetailAvailable]

    config_file = 'general_config.json'

    general_items = [
        'system.hostname',
        'system.sw.os',
        'system.sw.arch',
        'system.uptime',
        'system.boottime',
        'system.localtime',
        'system.users.num',
        'proc.num',
        'proc.num[,,run]',
        'kernel.maxfiles',
        'kernel.maxproc',
        'vfs.file.cksum[/etc/passwd,sha256]'
    ]

    date_data = [
        'system.boottime',
        'system.localtime'
    ]


class DiskDetailView(SystemDetailView):
    permission_classes = [IsAuthenticated, permission_for_view('DISK'), IsDetailAvailable]

    STATUS_FUNCTIONS = {
        'vfs.dev.queue_size': sc.main_status,
        'vfs.dev.read.await': sc.main_status,
        'vfs.dev.write.await': sc.main_status,
        'vfs.dev.read.time.rate': sc.main_status,
        'vfs.dev.write.time.rate': sc.main_status,
        'vfs.dev.util': sc.main_status,
    }

    config_file = 'disk_config.json'

    def get_disks(self, user_system):
        """Dynamically detect available disk partitions using Zabbix API"""
        zabbix_helper = ZabbixHelper(url=user_system.zabbix_details['url'],
                                     user=user_system.zabbix_details['username'],
                                     password=user_system.zabbix_details['password'],
                                     host_name=user_system.zabbix_details['host_name']
                                     )
        host_id = zabbix_helper.host_id

        items = zabbix_helper.zabbix.zabbix.item.get(hostids=host_id, output=["key_"])

        disks = []
        for item in items:
            if item['key_'].startswith("vfs.dev."):
                disk_name = item['key_'].split('[')[1].rstrip(']')  # Get the name inside brackets
                if disk_name not in disks:
                    disks.append(disk_name)

        return disks

    def get(self, request):
        try:
            user = request.user
            user_system = UserSystem.objects.filter(user=user).first()
            if not user_system:
                return create_response(success=False, message=mt[403], status=status.HTTP_401_UNAUTHORIZED)


            config = self.load_config(self.config_file)
            data = {}

            disks = self.get_disks(user_system)
            for disk in disks:
                general_items = [
                    f'vfs.dev.read.rate[{disk}]',
                    f'vfs.dev.write.rate[{disk}]'
                ]
                metric_items = [
                    f'vfs.dev.queue_size[{disk}]',
                    f'vfs.dev.read.await[{disk}]',
                    f'vfs.dev.write.await[{disk}]',
                    f'vfs.dev.read.time.rate[{disk}]',
                    f'vfs.dev.write.time.rate[{disk}]',
                    f'vfs.dev.util[{disk}]'
                ]

                disk_data = self.get_data(general_items, metric_items, config, user_system)
                data[disk] = disk_data

            return create_response(success=True, status=status.HTTP_200_OK, data=data, message=mt[200])
        except ValueError as e:
            return create_response(success=False, status=status.HTTP_500_INTERNAL_SERVER_ERROR, message=mt[500], data=e)


class NetworkInterfaceDetailView(SystemDetailView):
    permission_classes = [IsAuthenticated,  permission_for_view('NETWORK'), IsDetailAvailable]

    STATUS_FUNCTIONS = {
        'net.if.in.dropped': sc.main_status,
        'net.if.in.errors': sc.main_status,
        'net.if.out.dropped': sc.main_status,
        'net.if.out.errors': sc.main_status,
    }

    config_file = 'networkinterface_config.json'

    def get_interfaces(self, user_system):
        """Dynamically detect available network interfaces"""
        zabbix_helper = ZabbixHelper(url=user_system.zabbix_details['url'],
                                     user=user_system.zabbix_details['username'],
                                     password=user_system.zabbix_details['password'],
                                     host_name=user_system.zabbix_details['host_name']
                                     )
        host_id = zabbix_helper.host_id

        items = zabbix_helper.zabbix.zabbix.item.get(hostids=host_id, output=["key_"])

        interfaces = []
        for item in items:
            if item['key_'].startswith("net.if."):
                interface_name = item['key_'].split('"')[1] if '"' in item['key_'] else \
                    item['key_'].split('[')[1].split(']')[0]
                if interface_name not in interfaces:
                    interfaces.append(interface_name)

        return interfaces

    def get(self, request):
        try:
            user = request.user
            user_system = UserSystem.objects.filter(user=user).first()
            if not user_system:
                return create_response(success=False, message=mt[403], status=status.HTTP_401_UNAUTHORIZED)

            config = self.load_config(self.config_file)
            data = {}

            interfaces = self.get_interfaces(user_system)
            for interface in interfaces:
                general_items = [
                    f'net.if.in["{interface}"]',
                    f'net.if.out["{interface}"]',
                ]
                metric_items = [
                    f'net.if.in["{interface}",dropped]',
                    f'net.if.in["{interface}",errors]',
                    f'net.if.out["{interface}",dropped]',
                    f'net.if.out["{interface}",errors]',
                ]

                interface_data = self.get_data(general_items, metric_items, config, user_system)
                data[interface] = interface_data

            return create_response(success=True, status=status.HTTP_200_OK, data=data, message=mt[200])
        except ValueError as e:
            return create_response(success=False, status=status.HTTP_500_INTERNAL_SERVER_ERROR, message=str(e))
