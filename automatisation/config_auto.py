import json
import re
import time
import telnetlib
from ipaddress import IPv6Network
import sys

from gns3fy import Gns3Connector, Project, Node

GNS3_URL = "http://127.0.0.1:3080"         
DEFAULT_OSPF_AREA = 0
OSPF_PROCESS_ID = 1
TELNET_DELAY = 0.3

with open("intent.json", "r", encoding="utf-8") as f:
    intent = json.load(f)

server = Gns3Connector(url=GNS3_URL)
project = Project(name="structure_vide", connector=server)
project.get()      
project.open()     

project.get_nodes()
print([n.name for n in project.nodes])

for router_name, router_info in intent.get("routeurs", {}).items():

    node = Node(project_id=project.project_id, name=router_name, connector=server)
    node.get()

    tn = telnetlib.Telnet(node.console_host, node.console)
    time.sleep(1)

    tn.write(b"\r\n")
    time.sleep(0.5)

    tn.write(b"enable\r\n")
    time.sleep(0.3)

    tn.write(b"configure terminal\r\n")
    time.sleep(0.3)

    for link in intent["links"]:

        if router_name == link["routeur_a"]:
            tn.write()
            

        elif router_name == link["routeur_b"]:
            tn.write()
            
        else:
            continue

    tn.write(b"end\r\n")
    tn.write(b"write\r\n")

    tn.close()

    