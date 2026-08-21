import os,sys,types,math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
mqtt=types.ModuleType('paho.mqtt.client'); mqtt.CallbackAPIVersion=types.SimpleNamespace(VERSION2=2); mqtt.Client=object
sys.modules['paho']=types.ModuleType('paho');sys.modules['paho.mqtt']=types.ModuleType('paho.mqtt');sys.modules['paho.mqtt.client']=mqtt
from mqtt_manager import validar_geometria_l,triangulos,circulos,distancia
n=[{'node_id':'ESP32_0','pos_x':0.0,'pos_y':0.0},{'node_id':'ESP32_1','pos_x':5.0,'pos_y':0.0},{'node_id':'ESP32_2','pos_x':0.0,'pos_y':2.0}]
bounds=(5.0,2.0)
print('VALID_GEOMETRY',validar_geometria_l(n))
for p in [(0.5,0.5),(2,1),(4,1.5),(5,2)]:
 d=[math.hypot(p[0]-x['pos_x'],p[1]-x['pos_y']) for x in n]
 t=triangulos(d,n,bounds); c=circulos(d,n,bounds)
 print('POINT',p,'TRI',t,'TRI_ERR',distancia(p,t) if t else None,'CIRC',c,'CIRC_ERR',distancia(p,c) if c else None)
print('OUTSIDE_TRI',triangulos([math.hypot(6-x['pos_x'],1-x['pos_y']) for x in n],n,bounds))
print('IMPOSSIBLE_TRI',triangulos([1,1,10],n,bounds))
