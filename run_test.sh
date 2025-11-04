#!/bin/bash
# Integrated test script

cd /home/runner/work/CS3103_Assignment4_Group1/CS3103_Assignment4_Group1

echo "Starting server..."
python3 server.py > /tmp/server_test.log 2>&1 &
SERVER_PID=$!
sleep 2

echo "Running timeout test..."
python3 test_timeout.py

sleep 2

echo ""
echo "=== SERVER OUTPUT ==="
cat /tmp/server_test.log | grep -E "RELIABLE|TIMEOUT|Skipping|SERVER"

kill $SERVER_PID 2>/dev/null
wait $SERVER_PID 2>/dev/null

echo ""
echo "Test completed!"
