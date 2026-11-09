import urllib.request, json, time

BASE = 'http://127.0.0.1:8000/api/v1'

# Login
body = json.dumps({'email':'demo@test.com','password':'DemoPass123!'}).encode()
req = urllib.request.Request(f'{BASE}/auth/login', body, {'Content-Type':'application/json'}, method='POST')
tok = json.loads(urllib.request.urlopen(req, timeout=10).read())['access_token']
headers = {'Authorization': f'Bearer {tok}'}

# Dashboard
stats = json.loads(urllib.request.urlopen(urllib.request.Request(f'{BASE}/analytics/dashboard', headers=headers), timeout=10).read())
print(f'Dashboard: total={stats["total_messages"]} unread={stats["unread_messages"]}')

# Voicemails
vms = json.loads(urllib.request.urlopen(urllib.request.Request(f'{BASE}/voicemails', headers=headers), timeout=10).read())
print(f'Voicemails: total={vms["total"]} items={len(vms["items"])}')

if vms['items']:
    vm = vms['items'][0]
    vmid = vm['id']
    print(f'First voicemail: caller={vm.get("caller_number")} status={vm.get("processing_status")}')

    # Transcript
    trans = json.loads(urllib.request.urlopen(urllib.request.Request(f'{BASE}/voicemails/{vmid}/transcript', headers=headers), timeout=10).read())
    print(f'Transcript: has_transcript={trans["has_transcript"]}')
    if trans['has_transcript']:
        print(f'  language={trans["transcript"].get("detected_language")}')
        print(f'  text_len={len(trans["transcript"]["raw_text"])}')

    # Report
    report = json.loads(urllib.request.urlopen(urllib.request.Request(f'{BASE}/voicemails/{vmid}/report', headers=headers), timeout=10).read())
    print(f'Report: has_report={report["has_report"]}')
    if report['has_report']:
        print(f'  overall_status={report["overall_status"]}')
        print(f'  total_entities={report["total_entities"]}')

    # Audio check
    try:
        audio_resp = urllib.request.urlopen(urllib.request.Request(f'{BASE}/voicemails/{vmid}/audio', headers=headers), timeout=10)
        print(f'Audio: {audio_resp.status} content-type={audio_resp.headers.get("content-type")}')
    except Exception as e:
        print(f'Audio: error - {e}')

    # Corrections
    corr_body = json.dumps({'corrected_text': 'Test correction from demo', 'change_summary': 'Demo correction'}).encode()
    corr_req = urllib.request.Request(f'{BASE}/voicemails/{vmid}/corrections', corr_body, {**headers, 'Content-Type': 'application/json'}, method='POST')
    corr = json.loads(urllib.request.urlopen(corr_req, timeout=10).read())
    print(f'Correction: version={corr["version_number"]}')

    # Verify original unchanged
    trans2 = json.loads(urllib.request.urlopen(urllib.request.Request(f'{BASE}/voicemails/{vmid}/transcript', headers=headers), timeout=10).read())
    if trans2['has_transcript']:
        print(f'Immutability: original preserved={trans["transcript"]["raw_text"] == trans2["transcript"]["raw_text"]}')
else:
    print('No voicemails found - triggering test...')
    test_req = urllib.request.Request(f'{BASE}/telephony/test', headers=headers, method='POST')
    test = json.loads(urllib.request.urlopen(test_req, timeout=10).read())
    print(f'Test triggered: voicemail_id={test["voicemail_id"]}')
    print('Waiting 15s for processing...')
    time.sleep(15)
    # Check again
    vms2 = json.loads(urllib.request.urlopen(urllib.request.Request(f'{BASE}/voicemails', headers=headers), timeout=10).read())
    print(f'After wait: total={vms2["total"]} items={len(vms2["items"])}')
    if vms2['items']:
        print(f'Voicemail status: {vms2["items"][0]["processing_status"]}')

print('\nALL CHECKS COMPLETE')
