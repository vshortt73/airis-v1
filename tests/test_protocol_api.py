#!/usr/bin/env python3
"""Test protocol API endpoint"""
import requests
import json

# Test getting the default protocol
print("=== Testing GET /api/protocols/1 (default) ===")
response = requests.get("http://localhost:8000/api/protocols/1")
if response.status_code == 200:
    data = response.json()
    print(f"\nProtocol: {data['name']}")
    print(f"rules_include type: {type(data.get('rules_include'))}")
    print(f"rules_include value: {data.get('rules_include')}")
    print(f"rules_exclude type: {type(data.get('rules_exclude'))}")
    print(f"rules_exclude value: {data.get('rules_exclude')}")
    print(f"traits_adjust type: {type(data.get('traits_adjust'))}")
    print(f"Sample traits: {list(data.get('traits_adjust', {}).items())[:3]}")
else:
    print(f"Error: {response.status_code}")
    print(response.text)

# Test getting the Theta protocol (assuming ID 2)
print("\n\n=== Testing GET /api/protocols (list all) ===")
response = requests.get("http://localhost:8000/api/protocols")
if response.status_code == 200:
    data = response.json()
    print(f"Found {len(data['protocols'])} protocols:")
    for p in data['protocols']:
        print(f"  - ID {p['id']}: {p['name']}")

    # Find Theta
    theta_id = None
    for p in data['protocols']:
        if p['name'] == 'Theta':
            theta_id = p['id']
            break

    if theta_id:
        print(f"\n\n=== Testing GET /api/protocols/{theta_id} (Theta) ===")
        response = requests.get(f"http://localhost:8000/api/protocols/{theta_id}")
        if response.status_code == 200:
            data = response.json()
            print(f"\nProtocol: {data['name']}")
            print(f"rules_include type: {type(data.get('rules_include'))}")
            print(f"rules_include value: {data.get('rules_include')}")
            print(f"rules_exclude type: {type(data.get('rules_exclude'))}")
            print(f"rules_exclude value: {data.get('rules_exclude')}")
        else:
            print(f"Error: {response.status_code}")
else:
    print(f"Error: {response.status_code}")
