
import pytest
import os
import time
import fcntl
from pathlib import Path
from clawteam.transport.file import FileTransport
from clawteam.transport.p2p import P2PTransport
from clawteam.team.models import get_data_dir

@pytest.fixture
def transport(team_name):
    return FileTransport(team_name)

@pytest.fixture
def p2p_transport(team_name):
    t = P2PTransport(team_name, bind_agent="listener")
    yield t
    t.close()

def test_p2p_transport_deliver_and_fetch(team_name):
    # Receiver
    receiver = P2PTransport(team_name, bind_agent="bob")
    
    # Sender
    sender = P2PTransport(team_name)
    
    try:
        data = b"p2p message"
        sender.deliver("bob", data)
        
        # Fetch on receiver (should use ZMQ)
        # We might need a small sleep to allow ZMQ to connect and deliver
        time.sleep(0.2)
        
        fetched = receiver.fetch("bob", consume=True)
        assert len(fetched) == 1
        assert fetched[0] == data
        
    finally:
        receiver.close()
        sender.close()

def test_p2p_transport_fallback_to_file(team_name):
    # Sender only, no receiver listening on ZMQ
    sender = P2PTransport(team_name)
    
    try:
        data = b"fallback message"
        # Since "alice" is not registered as a peer, it should fall back to file
        sender.deliver("alice", data)
        
        # Check if file exists
        inbox_dir = get_data_dir() / "teams" / team_name / "inboxes" / "alice"
        files = list(inbox_dir.glob("msg-*.json"))
        assert len(files) == 1
        
        # Fetch should work via file fallback
        receiver = P2PTransport(team_name)
        fetched = receiver.fetch("alice", consume=True)
        assert fetched == [data]
        receiver.close()
    finally:
        sender.close()

def test_file_transport_deliver_and_fetch(transport, team_name):
    data = b"hello world"
    recipient = "agent1"
    
    transport.deliver(recipient, data)
    
    # Check if file exists in inbox
    inbox_dir = get_data_dir() / "teams" / team_name / "inboxes" / recipient
    files = list(inbox_dir.glob("msg-*.json"))
    assert len(files) == 1
    assert files[0].read_bytes() == data
    
    # Fetch (consume)
    fetched = transport.fetch(recipient, consume=True)
    assert len(fetched) == 1
    assert fetched[0] == data
    
    # Fetch again should be empty
    assert transport.fetch(recipient, consume=True) == []

def test_file_transport_claim_and_ack(transport, team_name):
    data = b"test message"
    recipient = "agent2"
    
    transport.deliver(recipient, data)
    
    # Claim
    claimed_msgs = transport.claim_messages(recipient)
    assert len(claimed_msgs) == 1
    claimed = claimed_msgs[0]
    assert claimed.data == data
    
    # While claimed, it should be marked as .consumed and locked
    inbox_dir = get_data_dir() / "teams" / team_name / "inboxes" / recipient
    consumed_files = list(inbox_dir.glob("msg-*.consumed"))
    assert len(consumed_files) == 1
    
    # Another claim should return nothing (because it's locked)
    assert transport.claim_messages(recipient) == []
    
    # Ack
    claimed.ack()
    
    # File should be gone
    assert not consumed_files[0].exists()
    assert transport.claim_messages(recipient) == []

def test_file_transport_quarantine(transport, team_name):
    data = b"bad message"
    recipient = "agent3"
    
    transport.deliver(recipient, data)
    claimed = transport.claim_messages(recipient)[0]
    
    # Quarantine
    claimed.quarantine("something went wrong")
    
    # Dead letter should exist
    dead_letter_dir = get_data_dir() / "teams" / team_name / "dead_letters" / recipient
    # Filter out .meta.json files
    dead_letters = [p for p in dead_letter_dir.glob("msg-*.json") if not p.name.endswith(".meta.json")]
    assert len(dead_letters) == 1
    assert dead_letters[0].read_bytes() == data
    
    # Meta file should exist
    meta_files = list(dead_letter_dir.glob("msg-*.meta.json"))
    assert len(meta_files) == 1

def test_file_transport_count_and_list_recipients(transport, team_name):
    transport.deliver("r1", b"m1")
    transport.deliver("r1", b"m2")
    transport.deliver("r2", b"m3")
    
    # list_recipients before any count side effects
    recipients = transport.list_recipients()
    assert set(recipients) == {"r1", "r2"}

    assert transport.count("r1") == 2
    assert transport.count("r2") == 1
    
    assert transport.count("r3") == 0
    # Bug fixed: count() no longer creates the directory
    assert "r3" not in transport.list_recipients()

def test_file_transport_fetch_without_consume(transport, team_name):
    data = b"peek me"
    recipient = "agent4"
    transport.deliver(recipient, data)
    
    # Fetch without consume
    fetched = transport.fetch(recipient, consume=False)
    assert len(fetched) == 1
    assert fetched[0] == data
    
    # Should still be there
    assert transport.count(recipient) == 1
    
    # Fetch with consume
    fetched_again = transport.fetch(recipient, consume=True)
    assert fetched_again == [data]
    assert transport.count(recipient) == 0
