
import pytest
from unittest.mock import MagicMock, patch
from clawteam.team.watcher import InboxWatcher

@pytest.fixture
def mock_mailbox():
    return MagicMock()

def test_watcher_polling(mock_mailbox):
    msg = MagicMock(
        timestamp="2026-03-24",
        type=MagicMock(value="message"),
        from_agent="alice",
        to="bob",
        content="hello"
    )
    # Return one message then stop the loop
    mock_mailbox.receive.side_effect = [[msg], []]
    
    watcher = InboxWatcher(
        team_name="test-team",
        agent_name="bob",
        mailbox=mock_mailbox,
        poll_interval=0.01
    )
    
    # We need a way to stop the loop after one poll
    # Patching time.sleep to stop the loop
    def stop_running(*args):
        watcher._running = False
        
    with patch("time.sleep", side_effect=stop_running):
        watcher.watch()
        
    assert mock_mailbox.receive.call_count >= 1
    mock_mailbox.receive.assert_any_call("bob", limit=10)

@patch("subprocess.run")
def test_watcher_exec_callback(mock_run, mock_mailbox):
    msg = MagicMock(
        timestamp="2026-03-24",
        type=MagicMock(value="message"),
        from_agent="alice",
        to="bob",
        content="hello"
    )
    msg.model_dump_json.return_value = '{"content": "hello"}'
    
    mock_mailbox.receive.side_effect = [[msg], []]
    
    watcher = InboxWatcher(
        team_name="test-team",
        agent_name="bob",
        mailbox=mock_mailbox,
        poll_interval=0.01,
        exec_cmd="echo $CLAWTEAM_MSG_CONTENT"
    )
    
    def stop_running(*args):
        watcher._running = False
        
    with patch("time.sleep", side_effect=stop_running):
        watcher.watch()
        
    assert mock_run.call_count == 1
    args, kwargs = mock_run.call_args
    assert args[0] == "echo $CLAWTEAM_MSG_CONTENT"
    assert kwargs["env"]["CLAWTEAM_MSG_CONTENT"] == "hello"
    assert kwargs["env"]["CLAWTEAM_MSG_FROM"] == "alice"
