# Executes actual mqtt_manager geometry code, stubbing only unavailable MQTT package.
import os, sys, types, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
mqtt_mod=types.ModuleType('paho.mqtt.client')
mqtt_mod.CallbackAPIVersion=types.SimpleNamespace(VERSION2=2)
mqtt_mod.Client=object
sys.modules['paho']=types.ModuleType('paho')
sys.modules['paho.mqtt']=types.ModuleType('paho.mqtt')
sys.modules['paho.mqtt.client']=mqtt_mod
from mqtt_manager import triangulos, circulos, distancia, disRSSI

nodes=[
 {'node_id':'ESP32_0','pos_x':0.0,'pos_y':0.0},
 {'node_id':'ESP32_1','pos_x':5.0,'pos_y':0.0},
 {'node_id':'ESP32_2','pos_x':0.0,'pos_y':2.0},
]
def ds(p): return [math.hypot(p[0]-n['pos_x'], p[1]-n['pos_y']) for n in nodes]
def fmt(v): return tuple(round(x,4) for x in v)
print('EXACT_KNOWN_POINTS')
for p in [(0.5,0.5),(2,1),(4,1.5),(6,4),(7.5,5.5)]:
 d=ds(p); tri=triangulos(d,nodes); circ=circulos(d,nodes)
 print({'real':p,'d':fmt(d),'tri':fmt(tri),'tri_error':round(distancia(tri,p),5),'circ':fmt(circ),'circ_error':round(distancia(circ,p),5)})
print('NOISY_2_1')
p=(2,1); exact=ds(p)
for noise in [(-.15,.08,.05),(.5,-.5,.3),(2,-2,1)]:
 d=[x+n for x,n in zip(exact,noise)]
 tri=triangulos(d,nodes); circ=circulos(d,nodes)
 print({'noise_m':noise,'tri':fmt(tri),'tri_error':round(distancia(tri,p),5),'circ':fmt(circ),'circ_error':round(distancia(circ,p),5)})
print('DEGENERATE_INPUTS')
for d in [[1,1,10],[0,1,1],[1,1,1]]:
 try: print('d',d,'tri',fmt(triangulos(d,nodes)),'circ',fmt(circulos(d,nodes)))
 except Exception as e: print('d',d,'ERROR',type(e).__name__,str(e))
print('RSSI_MODEL')
for rssi,A,n in [(-57.29,-57.29,3.76),(-67.29,-57.29,3.76),(-57.29,-57.29,0), (float('nan'),-57.29,3.76)]:
 try: print(rssi,A,n,disRSSI(rssi,A,n))
 except Exception as e: print(rssi,A,n,'ERROR',type(e).__name__,str(e))
