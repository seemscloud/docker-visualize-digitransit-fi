import os
import json
import time
import logging
import string
import random
import statistics
import certifi

import paho.mqtt.client as mqtt
import geopy.distance
# import numpy as np

from kafka import KafkaProducer, KafkaConsumer
from multiprocessing import Process, Queue
from threading import Thread
from prometheus_client import start_http_server, Counter, Gauge, multiprocess, CollectorRegistry

LOGLEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOGLEVEL)

geo_location = Gauge('geo_location', 'Geo Location Longitude', ["line", "longitude", "latitude"])

dataQueue = Queue()


def compose_headers():
    return [("timestamp", timestamp_ms().encode('utf_8'))]


def flush(self):
    self.producer.flush()


def mqtt_on_connect(client, userdata, flags, rc):
    print("Connected with result code", rc)


def mqtt_on_message(client, userdata, msg):
    data = json.loads(msg.payload)

    dataQueue.put(data)


def mqtt_data_loop(mqtt_proto, mqtt_server, mqtt_port, mqtt_topic):
    client = mqtt.Client(client_id="", clean_session=True, transport="tcp")

    client.on_connect = mqtt_on_connect
    client.on_message = mqtt_on_message

    if mqtt_proto == "mqtts":
        client.tls_set(certifi.where())

    client.connect(mqtt_server, mqtt_port, 10)
    client.subscribe(mqtt_topic)
    client.loop_forever()


def producer_loop(endpoints, topic, message_size, batch_size, linger_ms, compression_type, acks):
    if compression_type == "None":
        compression_type = None

    producer = KafkaProducer(bootstrap_servers=endpoints,
                             value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                             linger_ms=linger_ms, batch_size=batch_size, compression_type=compression_type,
                             acks=acks)

    while True:
        latencies = []
        for i in range(dataQueue.qsize()):
            latencies.append(dataQueue.get())

        if latencies:
            headers = compose_headers()
            for i in latencies:
                producer.send(topic, i, headers=headers)
                producer.flush()


class VehiclePosition:
    def __init__(self, longitude, latitude, line):
        self.longitude = longitude
        self.latitude = latitude
        self.line = line


def position_shift(old, new):
    if geopy.distance.geodesic((old.latitude, old.longitude), (new.latitude, new.longitude)).m > 100:
        return True

    return False


def find_vehicle(data, vehicle):
    for i in range(len(data)):
        if data[i].line == vehicle.line:
            result = position_shift(data[i], vehicle)
            if result:
                data[i] = vehicle
                return data, True
            return data, False

    return data, False


def add_vehicle(data, vehicle):
    data, update = find_vehicle(data, vehicle)

    if update:
        return data, False

    data.append(vehicle)
    return data, True


def consumer_loop(endpoints, topic, group_name):
    consumer = KafkaConsumer(topic, bootstrap_servers=endpoints, enable_auto_commit=False, group_id=group_name,
                             value_deserializer=lambda x: json.loads(x.decode('utf-8')))

    pub_trans = []

    for msg in consumer:
        data = msg.value

        dl = 0
        line = "unknown"

        try:
            if data['VP']['dl'] is not None:
                dl = data['VP']['dl']

            line = data['VP']['desi']

        except KeyError:
            line = "UNKNOWN"
            pass

        pub_trans, update = add_vehicle(pub_trans, VehiclePosition(data['VP']['long'], data['VP']['lat'], line))

        if update:
            geo_location.labels(longitude=data['VP']['long'],
                                latitude=data['VP']['lat'],
                                line=line).set(dl)


def random_string(n):
    return ''.join(random.choice(string.ascii_lowercase) for _ in range(n))


def to_bytes(data):
    return data.encode("UTF-8")


def timestamp_ms():
    return "{}".format(int(time.time() * 1000))


def parse_servers(data):
    return list(filter(None, data.split(",")))


def calc_delay(delay):
    return int(delay) * 0.001


def main():
    mqtt_proto = os.environ["MQTT_PROTO"]
    mqtt_server = os.environ["MQTT_SERVER"]
    mqtt_port = int(os.environ["MQTT_PORT"])
    mqtt_topic = os.environ["MQTT_TOPIC"]

    message_size = int(os.environ["MESSAGE_SIZE"])
    topic_name = os.environ["TOPIC_NAME"]
    group_name = os.environ["GROUP_NAME"]

    batch_size = int(os.environ["BATCH_SIZE"])
    linger_ms = int(os.environ["LINGER_MS"])
    compression_type = os.environ["COMPRESSION"]
    acks = os.environ["ACKS"]

    endpoints = parse_servers(os.environ["BOOTSTRAP_SERVERS"])

    Process(target=mqtt_data_loop, args=(mqtt_proto, mqtt_server, mqtt_port, mqtt_topic)).start()

    Process(target=producer_loop,
            args=(endpoints, topic_name, message_size, batch_size, linger_ms, compression_type, acks)).start()

    Process(target=consumer_loop, args=(endpoints, topic_name, group_name)).start()


if __name__ == "__main__":
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    start_http_server(8000, registry=registry)

    init_delay = calc_delay(os.environ["INIT_DELAY"])
    time.sleep(init_delay)

    main()
