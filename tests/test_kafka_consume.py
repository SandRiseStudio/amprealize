#!/usr/bin/env python3
"""Quick test to verify Kafka consumption works."""

import json
from kafka import KafkaConsumer

print("Creating consumer...")
consumer = KafkaConsumer(
    'telemetry.events',
    bootstrap_servers=['localhost:9092'],
    auto_offset_reset='earliest',
    group_id='test-consumer-group',
    value_deserializer=lambda m: json.loads(m.decode('utf-8')),
    consumer_timeout_ms=5000
)

print("Polling for messages...")
count = 0
for message in consumer:
    count += 1
    print(f"Message {count}: offset={message.offset}, event_type={message.value.get('event_type')}")
    if count >= 5:
        break

print(f"\nConsumed {count} messages successfully")
consumer.close()
