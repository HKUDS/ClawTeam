
import pytest
from unittest.mock import MagicMock, patch
from clawteam.team.waiter import TaskWaiter, WaitResult, TaskStatus

@pytest.fixture
def mock_mailbox():
    return MagicMock()

@pytest.fixture
def mock_task_store():
    return MagicMock()

def test_waiter_completion(mock_mailbox, mock_task_store):
    # Setup mock tasks: first poll has one in progress, second poll all completed
    task1 = MagicMock(id="1", subject="task1", status=TaskStatus.in_progress, owner="alice")
    task2 = MagicMock(id="1", subject="task1", status=TaskStatus.completed, owner="alice")
    
    mock_task_store.list_tasks.side_effect = [
        [task1],
        [task2],
    ]
    mock_mailbox.receive.return_value = []
    
    waiter = TaskWaiter(
        team_name="test-team",
        agent_name="leader",
        mailbox=mock_mailbox,
        task_store=mock_task_store,
        poll_interval=0.01
    )
    
    result = waiter.wait()
    
    assert result.status == "completed"
    assert result.total == 1
    assert result.completed == 1
    assert mock_task_store.list_tasks.call_count == 2

def test_waiter_timeout(mock_mailbox, mock_task_store):
    task = MagicMock(id="1", subject="task1", status=TaskStatus.in_progress, owner="alice")
    mock_task_store.list_tasks.return_value = [task]
    mock_mailbox.receive.return_value = []
    
    waiter = TaskWaiter(
        team_name="test-team",
        agent_name="leader",
        mailbox=mock_mailbox,
        task_store=mock_task_store,
        poll_interval=0.01,
        timeout=0.05
    )
    
    result = waiter.wait()
    
    assert result.status == "timeout"
    assert result.completed == 0
    assert result.in_progress == 1

def test_waiter_on_message_callback(mock_mailbox, mock_task_store):
    task = MagicMock(id="1", subject="task1", status=TaskStatus.completed, owner="alice")
    mock_task_store.list_tasks.return_value = [task]
    
    msg = MagicMock()
    mock_mailbox.receive.side_effect = [[msg], []]
    
    received_msgs = []
    def on_message(m):
        received_msgs.append(m)
        
    waiter = TaskWaiter(
        team_name="test-team",
        agent_name="leader",
        mailbox=mock_mailbox,
        task_store=mock_task_store,
        poll_interval=0.01,
        on_message=on_message
    )
    
    result = waiter.wait()
    
    assert result.status == "completed"
    assert len(received_msgs) == 1
    assert result.messages_received == 1

@patch("clawteam.spawn.registry.list_dead_agents")
def test_waiter_dead_agent_recovery(mock_list_dead, mock_mailbox, mock_task_store):
    # Setup: alice is dead and has an in_progress task
    mock_list_dead.return_value = ["alice"]
    
    task1 = MagicMock(id="t1", subject="task1", status=TaskStatus.in_progress, owner="alice")
    # After recovery, it should be pending (but our mock list_tasks will just return it)
    # We want to check if task_store.update was called
    
    # Poll 1: alice dead, task in_progress -> recovery triggered -> task2 (completed)
    # We'll make it complete on second poll to stop the waiter
    task2 = MagicMock(id="t1", subject="task1", status=TaskStatus.completed, owner="alice")
    
    mock_task_store.list_tasks.side_effect = [[task1], [task2]]
    mock_mailbox.receive.return_value = []
    
    waiter = TaskWaiter(
        team_name="test-team",
        agent_name="leader",
        mailbox=mock_mailbox,
        task_store=mock_task_store,
        poll_interval=0.01
    )
    
    result = waiter.wait()
    
    assert result.status == "completed"
    # Check if recovery was called
    mock_task_store.update.assert_called_with("t1", status=TaskStatus.pending)
