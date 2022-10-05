#!/bin/bash

prometheus \
    --storage.tsdb.retention.size=1KB \
    --config.file=/etc/prometheus/prometheus.yml