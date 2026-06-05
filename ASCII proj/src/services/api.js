const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000';

export const getBackendUrl = () => BACKEND_URL;
export const getWsUrl = (sessionId) => `${BACKEND_URL.replace(/^http/, 'ws')}/ws/stream/${sessionId}`;

export async function createSession(config = null, maxFps = 15, label = null) {
  const response = await fetch(`${BACKEND_URL}/sessions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      config,
      max_fps: maxFps,
      label,
    }),
  });
  if (!response.ok) {
    throw new Error(`Failed to create session: ${response.statusText}`);
  }
  return response.json();
}

export async function getSessionStats(sessionId) {
  const response = await fetch(`${BACKEND_URL}/sessions/${sessionId}`);
  if (!response.ok) {
    throw new Error(`Failed to get session stats: ${response.statusText}`);
  }
  return response.json();
}

export async function updateConfig(sessionId, configPatch) {
  const response = await fetch(`${BACKEND_URL}/sessions/${sessionId}/config`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(configPatch),
  });
  if (!response.ok) {
    throw new Error(`Failed to update config: ${response.statusText}`);
  }
  return response.json();
}

export async function stopSession(sessionId) {
  const response = await fetch(`${BACKEND_URL}/sessions/${sessionId}/stop`, {
    method: 'POST',
  });
  if (!response.ok && response.status !== 204) {
    throw new Error(`Failed to stop session: ${response.statusText}`);
  }
}

export async function createSnapshot(sessionId, label = null) {
  const response = await fetch(`${BACKEND_URL}/sessions/${sessionId}/snapshot`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ label }),
  });
  if (!response.ok) {
    if (response.status === 409) {
      throw new Error("No frames processed yet. Please start streaming before taking a snapshot.");
    }
    throw new Error(`Failed to create snapshot: ${response.statusText}`);
  }
  return response.json();
}

export async function listSnapshots(sessionId) {
  const response = await fetch(`${BACKEND_URL}/sessions/${sessionId}/snapshots`);
  if (!response.ok) {
    throw new Error(`Failed to list snapshots: ${response.statusText}`);
  }
  return response.json();
}

export async function getSnapshot(snapshotId) {
  const response = await fetch(`${BACKEND_URL}/snapshots/${snapshotId}`);
  if (!response.ok) {
    throw new Error(`Failed to get snapshot: ${response.statusText}`);
  }
  return response.json();
}
