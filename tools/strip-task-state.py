#!/usr/bin/env python3
"""
Strip runtime state from a midPoint task export, leaving the definition.

A task exported after it has run carries operation result trees, counters and
timestamps. Those change on every run and bury the configuration in the diff.
This keeps what defines the task and drops what records its history.

Usage: strip-task-state.py FILE [FILE ...]
"""
import re, sys
import xml.etree.ElementTree as ET

BLOCKS = ["_metadata", "operationStats", "activityState", "result", "affectedObjects"]
LINES  = ["progress", "resultStatus", "schedulingState", "executionState",
          "stateBeforeSuspend", "schedulingStateBeforeSuspend", "taskIdentifier",
          "lastRunStartTimestamp", "lastRunFinishTimestamp", "completionTimestamp",
          "node", "nodeAsObserved"]

def strip(s):
    for b in BLOCKS:
        s = re.sub(rf"\n[ \t]*<{b}>.*?</{b}>", "", s, flags=re.S)
        s = re.sub(rf"\n[ \t]*<{b}/>", "", s)
    for l in LINES:
        s = re.sub(rf"\n[ \t]*<{l}>[^<]*</{l}>", "", s)
        s = re.sub(rf"\n[ \t]*<{l}/>", "", s)
    return re.sub(r'\s+version="[^"]*"', "", s, count=1)

for p in sys.argv[1:]:
    before = open(p).read()
    after = strip(before)
    try:
        ET.fromstring(after)
    except ET.ParseError as e:
        print(f"{p}: ABORTADO, XML invalido apos remocao ({e}). Nada gravado.")
        continue
    open(p, "w").write(after)
    print(f"{p}: {len(before.splitlines())} -> {len(after.splitlines())} linhas")
