import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Camera, CameraOff, Settings, RefreshCw, Copy, Check, Play, Square, 
  Image as ImageIcon, AlertCircle, RefreshCcw, Download, Sparkles, 
  Sliders, Cpu, Activity, LogOut, CheckCircle, HelpCircle, Layers, Monitor
} from 'lucide-react';
import { 
  createSession, updateConfig, stopSession, createSnapshot, 
  listSnapshots, getWsUrl, getSessionStats 
} from './services/api';

const CHARSETS = {
  default: " .:-=+*#%@",
  dense: " .'`^\",:;Il!i><~+_-?][}{1)(|/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$",
  blocks: " ░▒▓█",
  minimal: " .+#",
  braille: " ⠂⠆⠖⠶⠷⠿⣿",
};

const THEMES = {
  mono: { name: 'Monochrome', fg: '#f5f5f5', bg: '#0a0a0a', class: 'glow-effect' },
  green: { name: 'Green Terminal', fg: '#39ff14', bg: '#000000', class: 'glow-green text-[#39ff14]' },
  amber: { name: 'Amber Phosphor', fg: '#ffb000', bg: '#0d0800', class: 'glow-amber text-[#ffb000]' },
  cyan: { name: 'Cyan cold', fg: '#00e5ff', bg: '#000a0d', class: 'glow-cyan text-[#00e5ff]' },
  color: { name: 'True Color', fg: '#ffffff', bg: '#000000', class: 'glow-effect' },
  neon: { name: 'Cyberpunk Neon', fg: '#ff00ff', bg: '#05000f', class: 'glow-effect' },
  sepia: { name: 'Warm Sepia', fg: '#c8a97e', bg: '#1a1007', class: 'glow-effect text-[#c8a97e]' },
};

function App() {
  // Navigation & Session
  const [isAppLaunched, setIsAppLaunched] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [sessionLabel, setSessionLabel] = useState('My Stream');
  const [connectionStatus, setConnectionStatus] = useState('DISCONNECTED'); // DISCONNECTED, CONNECTING, CONNECTED
  
  // Media Devices
  const [devices, setDevices] = useState([]);
  const [selectedDevice, setSelectedDevice] = useState('');
  const [cameraActive, setCameraActive] = useState(false);
  const [cameraError, setCameraError] = useState(null);

  // Configuration
  const [config, setConfig] = useState({
    flip_horizontal: true,
    flip_vertical: false,
    ascii_width: 120,
    ascii_charset: 'default',
    theme_id: 'mono',
    invert: false,
    brightness: 1.0,
    contrast: 1.0,
  });
  
  const [customCharset, setCustomCharset] = useState(' .:-=+*#%@');
  const [localFps, setLocalFps] = useState(15);
  
  // Streaming Payloads
  const [latestPayload, setLatestPayload] = useState(null);
  const [sessionStats, setSessionStats] = useState({
    frames_received: 0,
    frames_processed: 0,
    frames_dropped: 0,
    effective_fps: 0,
  });

  // Snapshots
  const [snapshots, setSnapshots] = useState([]);
  const [selectedSnapshot, setSelectedSnapshot] = useState(null);
  const [newSnapshotLabel, setNewSnapshotLabel] = useState('');
  const [isTakingSnapshot, setIsTakingSnapshot] = useState(false);
  const [showSnapshotsList, setShowSnapshotsList] = useState(false);

  // UI Utilities
  const [copiedText, setCopiedText] = useState(false);
  const [copiedHtml, setCopiedHtml] = useState(false);
  const [showSettingsDrawer, setShowSettingsDrawer] = useState(true);

  // Refs for camera loop
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const wsRef = useRef(null);
  const timerRef = useRef(null);
  const statsIntervalRef = useRef(null);
  const activeStreamRef = useRef(null);

  // Get list of cameras
  useEffect(() => {
    async function getCameras() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: true });
        stream.getTracks().forEach(track => track.stop()); // close immediately to just query
        
        const allDevices = await navigator.mediaDevices.enumerateDevices();
        const videoInputDevices = allDevices.filter(device => device.kind === 'videoinput');
        setDevices(videoInputDevices);
        if (videoInputDevices.length > 0) {
          setSelectedDevice(videoInputDevices[0].deviceId);
        }
      } catch (err) {
        console.error("Error listing camera devices:", err);
        setCameraError("Camera access denied or no camera found.");
      }
    }
    if (isAppLaunched) {
      getCameras();
    }
  }, [isAppLaunched]);

  // Sync config changes with backend
  useEffect(() => {
    if (!sessionId) return;
    
    const timer = setTimeout(async () => {
      try {
        const actualCharset = config.ascii_charset === 'custom' ? customCharset : config.ascii_charset;
        await updateConfig(sessionId, {
          ...config,
          ascii_charset: actualCharset
        });
      } catch (err) {
        console.error("Failed to patch config:", err);
      }
    }, 150); // slight debounce

    return () => clearTimeout(timer);
  }, [config, customCharset, sessionId]);

  // Fetch session stats regularly when streaming
  useEffect(() => {
    if (connectionStatus === 'CONNECTED' && sessionId) {
      statsIntervalRef.current = setInterval(async () => {
        try {
          const stats = await getSessionStats(sessionId);
          setSessionStats(stats);
        } catch (err) {
          console.error("Failed to fetch session stats:", err);
        }
      }, 5000);
    } else {
      if (statsIntervalRef.current) {
        clearInterval(statsIntervalRef.current);
      }
    }
    return () => {
      if (statsIntervalRef.current) {
        clearInterval(statsIntervalRef.current);
      }
    };
  }, [connectionStatus, sessionId]);

  // Frame Capture and WebSocket loop
  const startStreaming = async () => {
    setCameraError(null);
    setConnectionStatus('CONNECTING');
    
    let activeSessionId = sessionId;

    try {
      // 1. Create session if not exists
      if (!activeSessionId) {
        const actualCharset = config.ascii_charset === 'custom' ? customCharset : config.ascii_charset;
        const session = await createSession(
          { ...config, ascii_charset: actualCharset },
          localFps,
          sessionLabel
        );
        activeSessionId = session.session_id;
        setSessionId(activeSessionId);
      }

      // 2. Open camera feed
      const constraints = {
        video: selectedDevice ? { deviceId: { exact: selectedDevice } } : true
      };
      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      activeStreamRef.current = stream;
      
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
        setCameraActive(true);
      }

      // 3. Connect WebSocket
      const wsUrl = getWsUrl(activeSessionId);
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnectionStatus('CONNECTED');
        refreshSnapshotsList(activeSessionId);
        
        let isProcessing = false;
        const intervalMs = Math.round(1000 / localFps);
        
        timerRef.current = setInterval(() => {
          if (!videoRef.current || !canvasRef.current || ws.readyState !== WebSocket.OPEN) return;
          if (isProcessing) return;

          const video = videoRef.current;
          const canvas = canvasRef.current;
          
          if (video.readyState === video.HAVE_ENOUGH_DATA) {
            isProcessing = true;
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
            
            canvas.toBlob((blob) => {
              if (blob && ws.readyState === WebSocket.OPEN) {
                ws.send(blob);
              }
              isProcessing = false;
            }, 'image/jpeg', 0.7);
          }
        }, intervalMs);
      };

      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.ping) return;
          setLatestPayload(payload);
        } catch (err) {
          console.error("Failed to parse socket message:", err);
        }
      };

      ws.onclose = () => {
        stopLocalStreamOnly();
      };

      ws.onerror = (err) => {
        console.error("WebSocket error:", err);
        setCameraError("WebSocket pipeline error occurred.");
        stopLocalStreamOnly();
      };

    } catch (err) {
      console.error("Error setting up pipeline:", err);
      setCameraError(err.message || "Failed to launch pipeline. Check backend connection.");
      setConnectionStatus('DISCONNECTED');
      stopLocalStreamOnly();
    }
  };

  const stopLocalStreamOnly = () => {
    setConnectionStatus('DISCONNECTED');
    setCameraActive(false);
    
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    
    if (activeStreamRef.current) {
      activeStreamRef.current.getTracks().forEach(track => track.stop());
      activeStreamRef.current = null;
    }
    
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  };

  const stopPipeline = async () => {
    stopLocalStreamOnly();
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (sessionId) {
      try {
        await stopSession(sessionId);
      } catch (err) {
        console.error("Failed to stop session on backend:", err);
      }
      setSessionId(null);
    }
    setLatestPayload(null);
    setSnapshots([]);
  };

  // Re-adjust capturing rate dynamically
  useEffect(() => {
    if (connectionStatus === 'CONNECTED' && timerRef.current) {
      clearInterval(timerRef.current);
      
      let isProcessing = false;
      const intervalMs = Math.round(1000 / localFps);
      
      timerRef.current = setInterval(() => {
        if (!videoRef.current || !canvasRef.current || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
        if (isProcessing) return;

        const video = videoRef.current;
        const canvas = canvasRef.current;
        
        if (video.readyState === video.HAVE_ENOUGH_DATA) {
          isProcessing = true;
          canvas.width = video.videoWidth;
          canvas.height = video.videoHeight;
          const ctx = canvas.getContext('2d');
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          
          canvas.toBlob((blob) => {
            if (blob && wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
              wsRef.current.send(blob);
            }
            isProcessing = false;
          }, 'image/jpeg', 0.7);
        }
      }, intervalMs);
    }
  }, [localFps, connectionStatus]);

  // Clean up on component unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (statsIntervalRef.current) clearInterval(statsIntervalRef.current);
      if (activeStreamRef.current) {
        activeStreamRef.current.getTracks().forEach(track => track.stop());
      }
    };
  }, []);

  // Snapshot Management
  const refreshSnapshotsList = async (id) => {
    const targetId = id || sessionId;
    if (!targetId) return;
    try {
      const data = await listSnapshots(targetId);
      setSnapshots(data.snapshots);
    } catch (err) {
      console.error("Failed to list snapshots:", err);
    }
  };

  const takeSnapshot = async () => {
    if (!sessionId) return;
    setIsTakingSnapshot(true);
    setCameraError(null);
    try {
      const label = newSnapshotLabel.trim() || `Snapshot #${snapshots.length + 1}`;
      await createSnapshot(sessionId, label);
      setNewSnapshotLabel('');
      await refreshSnapshotsList(sessionId);
    } catch (err) {
      console.error("Failed to take snapshot:", err);
      setCameraError(err.message || "Failed to persist snapshot.");
    } finally {
      setIsTakingSnapshot(false);
    }
  };

  const copyToClipboard = (text, isHtml = false) => {
    navigator.clipboard.writeText(text).then(() => {
      if (isHtml) {
        setCopiedHtml(true);
        setTimeout(() => setCopiedHtml(false), 2000);
      } else {
        setCopiedText(true);
        setTimeout(() => setCopiedText(false), 2000);
      }
    }).catch(err => {
      console.error("Failed to copy clipboard:", err);
    });
  };

  const downloadHtml = (htmlContent, label) => {
    if (!htmlContent) return;
    const blob = new Blob([htmlContent], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${label || 'ascii_art'}.html`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const getThemeConfig = () => {
    return THEMES[config.theme_id] || THEMES.mono;
  };

  return (
    <div className="relative min-h-screen w-full bg-black text-slate-100 overflow-x-hidden flex flex-col font-sans">
      
      {/* Shared Background Video */}
      <video 
        autoPlay 
        loop 
        muted 
        playsInline 
        className="absolute inset-0 w-full h-full object-cover z-0 pointer-events-none"
      >
        <source src="/nail_video.mp4" type="video/mp4" /> 
      </video>

      {/* Shared Background Overlay with smooth transitions */}
      <div 
        className={`absolute inset-0 z-0 pointer-events-none transition-all duration-1000 ${
          isAppLaunched ? 'bg-black/85 backdrop-blur-[6px]' : 'bg-black/40'
        }`} 
      />

      <AnimatePresence mode="wait">
        {!isAppLaunched ? (
          /* User's Original Video Hero Landing Page */
          <motion.div 
            key="landing"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="relative min-h-screen w-full text-white overflow-hidden flex flex-col items-center justify-center bg-transparent"
          >
            {/* Hero Content */}
            <main className="relative z-10 flex-1 flex flex-col items-center justify-center text-center px-4 w-full h-full">
              
              {/* Headline */}
              <motion.h1 
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 1, delay: 0.2, ease: "easeOut" }}
                className="text-5xl md:text-7xl lg:text-[100px] font-serif leading-[1] tracking-tight mb-12 text-white drop-shadow-2xl"
              >
                <span className="block">Superintelligence</span>
                <span className="block text-white/90">on-device</span>
              </motion.h1>

              {/* CTA */}
              <motion.button 
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.8, delay: 0.4, ease: "easeOut" }}
                onClick={() => setIsAppLaunched(true)}
                className="px-6 py-2.5 rounded-full bg-white/5 backdrop-blur-md border border-white/20 text-white/90 hover:bg-white hover:text-black transition-all duration-300 font-sans text-[11px] font-bold tracking-[0.15em] flex items-center justify-center gap-2 cursor-pointer"
              >
                LAUNCH APP <span className="text-lg leading-none font-normal mb-[2px]">→</span>
              </motion.button>
            </main>
          </motion.div>
        ) : (
          /* Main Dashboard */
          <motion.div 
            key="dashboard"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="relative z-10 flex-1 flex flex-col w-full"
          >
            {/* Header */}
            <header className="w-full px-6 py-4 border-b border-white/5 flex flex-wrap items-center justify-between gap-4 bg-black/60 backdrop-blur-md sticky top-0 z-20">
              <div className="flex items-center gap-3.5">
                <div className="w-2.5 h-2.5 rounded-full bg-white animate-pulse glow-effect" />
                <h2 className="text-sm font-semibold tracking-wider uppercase text-white font-mono">
                  ASCII_STREAM.EXE
                </h2>
                
                {sessionId && (
                  <span className="text-[10px] px-2 py-0.5 rounded bg-white/5 border border-white/5 font-mono text-slate-400">
                    SID: {sessionId.substring(0, 8)}...
                  </span>
                )}
              </div>

              {/* Status & Exit */}
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2 px-3 py-1 rounded-full border bg-white/2 border-white/5">
                  <span className={`w-2 h-2 rounded-full ${
                    connectionStatus === 'CONNECTED' ? 'bg-green-500 animate-ping' :
                    connectionStatus === 'CONNECTING' ? 'bg-amber-500 animate-spin border border-dashed' :
                    'bg-slate-600'
                  }`} />
                  <span className="text-[10px] font-mono tracking-widest text-slate-300 font-bold uppercase">
                    {connectionStatus}
                  </span>
                </div>

                <button 
                  onClick={() => {
                    stopPipeline();
                    setIsAppLaunched(false);
                  }}
                  className="p-2 rounded-lg bg-white/5 border border-white/5 text-slate-400 hover:text-white hover:bg-red-500/20 hover:border-red-500/30 transition-all cursor-pointer"
                  title="Stop and Exit to Intro Page"
                >
                  <LogOut className="w-4 h-4" />
                </button>
              </div>
            </header>

            {/* Error Message banner */}
            {cameraError && (
              <div className="mx-6 mt-4 p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-300 text-xs flex items-center gap-3">
                <AlertCircle className="w-4 h-4 text-red-400 shrink-0" />
                <span>{cameraError}</span>
              </div>
            )}

            {/* Main Section Grid */}
            <div className="flex-1 w-full p-6 flex flex-col lg:flex-row gap-6 max-w-8xl mx-auto">
              
              {/* Left Column: Camera and Control Panel */}
              <div className={`w-full lg:w-96 flex flex-col gap-6 shrink-0 transition-all ${
                showSettingsDrawer ? 'block' : 'hidden lg:block lg:opacity-50'
              }`}>
                
                {/* Camera Feed Preview */}
                <div className="glass-panel rounded-2xl p-4 overflow-hidden relative">
                  <h3 className="text-xs uppercase tracking-widest text-slate-400 font-bold mb-3 flex items-center gap-2">
                    <Monitor className="w-3.5 h-3.5 text-white/70" />
                    Input Pipeline
                  </h3>
                  
                  <div className="relative aspect-video rounded-xl bg-black overflow-hidden border border-white/5 flex items-center justify-center">
                    <video 
                      ref={videoRef} 
                      className={`w-full h-full object-cover ${config.flip_horizontal ? 'scale-x-[-1]' : ''} ${config.flip_vertical ? 'scale-y-[-1]' : ''}`} 
                      muted 
                      playsInline 
                      style={{ display: cameraActive ? 'block' : 'none' }}
                    />
                    
                    {!cameraActive && (
                      <div className="flex flex-col items-center gap-2 text-slate-600">
                        <CameraOff className="w-8 h-8" />
                        <span className="text-[10px] tracking-wider uppercase font-bold">No Feed Active</span>
                      </div>
                    )}
                    
                    {/* Device Selection Overlay */}
                    <div className="absolute bottom-2 left-2 right-2 flex gap-2">
                      <select 
                        value={selectedDevice} 
                        onChange={(e) => {
                          setSelectedDevice(e.target.value);
                          if (cameraActive) {
                            stopLocalStreamOnly();
                            setTimeout(startStreaming, 100);
                          }
                        }}
                        disabled={devices.length <= 1}
                        className="flex-1 text-[10px] px-2.5 py-1.5 rounded-lg bg-black/80 backdrop-blur border border-white/10 text-slate-300 focus:outline-none"
                      >
                        {devices.map(device => (
                          <option key={device.deviceId} value={device.deviceId}>
                            {device.label || `Camera ${devices.indexOf(device) + 1}`}
                          </option>
                        ))}
                      </select>
                      
                      <button
                        onClick={cameraActive ? stopLocalStreamOnly : startStreaming}
                        className={`p-1.5 rounded-lg border text-white transition-all cursor-pointer ${
                          cameraActive ? 'bg-red-500/20 border-red-500/30 hover:bg-red-500/40' : 'bg-white/10 border-white/20 hover:bg-white hover:text-black hover:border-white'
                        }`}
                      >
                        {cameraActive ? <Square className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5 fill-current" />}
                      </button>
                    </div>
                  </div>
                </div>

                {/* Processing adjustments card */}
                <div className="glass-panel rounded-2xl p-5 flex flex-col gap-5 flex-1">
                  <div className="flex justify-between items-center border-b border-white/5 pb-3">
                    <h3 className="text-xs uppercase tracking-widest text-slate-300 font-bold flex items-center gap-2">
                      <Sliders className="w-4 h-4 text-white/70" />
                      Adjustments
                    </h3>
                    <button 
                      onClick={() => setConfig({
                        flip_horizontal: true,
                        flip_vertical: false,
                        ascii_width: 120,
                        ascii_charset: 'default',
                        theme_id: 'mono',
                        invert: false,
                        brightness: 1.0,
                        contrast: 1.0,
                      })}
                      className="text-[10px] text-slate-500 hover:text-white flex items-center gap-1 cursor-pointer"
                    >
                      <RefreshCcw className="w-3 h-3" /> Reset
                    </button>
                  </div>

                  {/* Brightness slider */}
                  <div className="flex flex-col gap-1.5">
                    <div className="flex justify-between text-xs font-mono">
                      <span className="text-slate-400">Brightness</span>
                      <span className="text-white font-semibold">{config.brightness.toFixed(1)}x</span>
                    </div>
                    <input 
                      type="range" 
                      min="0.1" 
                      max="3.0" 
                      step="0.1"
                      value={config.brightness} 
                      onChange={(e) => setConfig({ ...config, brightness: parseFloat(e.target.value) })}
                      className="w-full h-1 bg-white/15 rounded-lg appearance-none cursor-pointer accent-white"
                    />
                  </div>

                  {/* Contrast slider */}
                  <div className="flex flex-col gap-1.5">
                    <div className="flex justify-between text-xs font-mono">
                      <span className="text-slate-400">Contrast</span>
                      <span className="text-white font-semibold">{config.contrast.toFixed(1)}x</span>
                    </div>
                    <input 
                      type="range" 
                      min="0.1" 
                      max="3.0" 
                      step="0.1"
                      value={config.contrast} 
                      onChange={(e) => setConfig({ ...config, contrast: parseFloat(e.target.value) })}
                      className="w-full h-1 bg-white/15 rounded-lg appearance-none cursor-pointer accent-white"
                    />
                  </div>

                  {/* Ascii Width slider */}
                  <div className="flex flex-col gap-1.5">
                    <div className="flex justify-between text-xs font-mono">
                      <span className="text-slate-400">ASCII Grid Width</span>
                      <span className="text-white font-semibold">{config.ascii_width} chars</span>
                    </div>
                    <input 
                      type="range" 
                      min="20" 
                      max="240" 
                      step="5"
                      value={config.ascii_width} 
                      onChange={(e) => setConfig({ ...config, ascii_width: parseInt(e.target.value) })}
                      className="w-full h-1 bg-white/15 rounded-lg appearance-none cursor-pointer accent-white"
                    />
                  </div>

                  {/* Target capture FPS slider */}
                  <div className="flex flex-col gap-1.5">
                    <div className="flex justify-between text-xs font-mono">
                      <span className="text-slate-400">Capture FPS Rate</span>
                      <span className="text-white font-semibold">{localFps} fps</span>
                    </div>
                    <input 
                      type="range" 
                      min="1" 
                      max="60" 
                      step="1"
                      value={localFps} 
                      onChange={(e) => setLocalFps(parseInt(e.target.value))}
                      className="w-full h-1 bg-white/15 rounded-lg appearance-none cursor-pointer accent-white"
                    />
                  </div>

                  {/* Charset select preset */}
                  <div className="flex flex-col gap-2">
                    <label className="text-xs text-slate-400 font-mono">Character Set</label>
                    <select 
                      value={config.ascii_charset}
                      onChange={(e) => setConfig({ ...config, ascii_charset: e.target.value })}
                      className="w-full px-3 py-2 rounded-xl bg-white/5 border border-white/10 text-slate-300 text-sm focus:outline-none focus:border-white/40"
                    >
                      <option value="default">Default Preset (Short)</option>
                      <option value="dense">Dense Preset (Detailed)</option>
                      <option value="blocks">Blocks Preset (Filled)</option>
                      <option value="minimal">Minimal preset (Sparse)</option>
                      <option value="braille">Braille preset (Points)</option>
                      <option value="custom">Custom Charset...</option>
                    </select>

                    {config.ascii_charset === 'custom' && (
                      <input 
                        type="text"
                        value={customCharset}
                        onChange={(e) => setCustomCharset(e.target.value)}
                        placeholder="e.g. #.-+"
                        maxLength={64}
                        className="mt-1 w-full px-3 py-2 rounded-xl bg-white/5 border border-white/20 text-white placeholder-slate-600 focus:outline-none font-mono text-sm focus:border-white/40"
                      />
                    )}
                  </div>

                  {/* Switches layout */}
                  <div className="grid grid-cols-2 gap-3 mt-2 border-t border-white/5 pt-4">
                    <button
                      onClick={() => setConfig({ ...config, flip_horizontal: !config.flip_horizontal })}
                      className={`px-3 py-2.5 rounded-xl border text-xs font-mono flex items-center justify-center gap-1.5 transition-all cursor-pointer ${
                        config.flip_horizontal ? 'bg-white/10 border-white/30 text-white' : 'bg-transparent border-white/5 text-slate-500'
                      }`}
                    >
                      Flip Horizontal
                    </button>
                    
                    <button
                      onClick={() => setConfig({ ...config, flip_vertical: !config.flip_vertical })}
                      className={`px-3 py-2.5 rounded-xl border text-xs font-mono flex items-center justify-center gap-1.5 transition-all cursor-pointer ${
                        config.flip_vertical ? 'bg-white/10 border-white/30 text-white' : 'bg-transparent border-white/5 text-slate-500'
                      }`}
                    >
                      Flip Vertical
                    </button>

                    <button
                      onClick={() => setConfig({ ...config, invert: !config.invert })}
                      className={`px-3 py-2.5 rounded-xl border text-xs font-mono flex items-center justify-center gap-1.5 transition-all cursor-pointer ${
                        config.invert ? 'bg-white/10 border-white/30 text-white' : 'bg-transparent border-white/5 text-slate-500'
                      }`}
                    >
                      Invert Lightness
                    </button>
                  </div>
                </div>
              </div>

              {/* Center/Right Column: Live ASCII viewport */}
              <div className="flex-1 flex flex-col gap-6 min-w-0">
                
                {/* Viewport Card */}
                <div className="glass-panel rounded-3xl p-6 flex flex-col flex-1 min-h-[500px] relative">
                  
                  {/* Viewport Header */}
                  <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/5 pb-4 mb-4">
                    <div className="flex items-center gap-3">
                      <div className="flex gap-1.5">
                        <span className="w-3 h-3 rounded-full bg-red-500/80" />
                        <span className="w-3 h-3 rounded-full bg-yellow-500/80" />
                        <span className="w-3 h-3 rounded-full bg-green-500/80" />
                      </div>
                      <span className="text-xs text-slate-400 font-mono">live_renderer_output.html</span>
                    </div>

                    <div className="flex items-center gap-3">
                      {/* Theme selection */}
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] uppercase font-bold text-slate-500 font-mono">Palette:</span>
                        <select
                          value={config.theme_id}
                          onChange={(e) => setConfig({ ...config, theme_id: e.target.value })}
                          className="px-2.5 py-1 rounded-lg bg-white/5 border border-white/10 text-xs text-slate-300 font-mono focus:outline-none"
                        >
                          {Object.entries(THEMES).map(([tid, details]) => (
                            <option key={tid} value={tid}>{details.name}</option>
                          ))}
                        </select>
                      </div>

                      {/* Control panel collapse */}
                      <button 
                        onClick={() => setShowSettingsDrawer(!showSettingsDrawer)}
                        className="px-2.5 py-1.5 rounded-lg bg-white/5 border border-white/10 text-xs text-slate-400 hover:text-white transition-all font-mono lg:hidden cursor-pointer"
                      >
                        Adjustments
                      </button>
                    </div>
                  </div>

                  {/* The ASCII Container Panel */}
                  <div 
                    className="flex-1 w-full rounded-2xl overflow-auto border border-white/5 p-4 flex items-center justify-center font-mono select-all select-text"
                    style={{ 
                      backgroundColor: getThemeConfig().bg, 
                      color: getThemeConfig().fg 
                    }}
                  >
                    {latestPayload ? (
                      config.theme_id === 'mono' ? (
                        <pre className="text-[10px] leading-[1.2] font-mono m-0 select-all p-2 select-text" style={{ whiteSpace: 'pre' }}>
                          {latestPayload.ascii_text}
                        </pre>
                      ) : (
                        <div 
                          dangerouslySetInnerHTML={{ __html: latestPayload.html_colored_ascii }}
                          className="m-0 overflow-visible text-[10px] select-all select-text"
                        />
                      )
                    ) : (
                      <div className="flex flex-col items-center gap-3 text-slate-600 max-w-sm text-center">
                        <Sparkles className="w-10 h-10 text-white/30 animate-pulse" />
                        <h4 className="text-sm font-semibold text-slate-500 tracking-wider uppercase font-mono">Pipeline Idle</h4>
                        <p className="text-xs font-light text-slate-600 font-mono">
                          Start the input camera feed and connect the WebSocket stream to begin ASCII rendering.
                        </p>
                        
                        {connectionStatus !== 'CONNECTED' && (
                          <button
                            onClick={startStreaming}
                            className="mt-2 px-5 py-2.5 rounded-xl bg-white text-black font-mono font-bold text-xs hover:bg-zinc-200 transition-all cursor-pointer animate-bounce"
                          >
                            CONNECT WS STREAM
                          </button>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Viewport Toolbar controls */}
                  {latestPayload && (
                    <div className="flex flex-wrap items-center justify-between gap-4 mt-4 border-t border-white/5 pt-4">
                      
                      {/* Copy actions */}
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => copyToClipboard(latestPayload.ascii_text, false)}
                          className="px-3.5 py-2 rounded-xl bg-white/5 border border-white/5 text-xs text-slate-300 hover:text-white hover:bg-white/10 transition-all flex items-center gap-2 cursor-pointer"
                        >
                          {copiedText ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
                          Copy Plain Text
                        </button>
                        
                        {latestPayload.html_colored_ascii && (
                          <button
                            onClick={() => copyToClipboard(latestPayload.html_colored_ascii, true)}
                            className="px-3.5 py-2 rounded-xl bg-white/5 border border-white/5 text-xs text-slate-300 hover:text-white hover:bg-white/10 transition-all flex items-center gap-2 cursor-pointer"
                          >
                            {copiedHtml ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
                            Copy Styled HTML
                          </button>
                        )}
                      </div>

                      {/* Snapshot Form */}
                      <div className="flex items-center gap-2">
                        <input 
                          type="text" 
                          placeholder="Snapshot label..."
                          value={newSnapshotLabel}
                          onChange={(e) => setNewSnapshotLabel(e.target.value)}
                          className="px-3 py-2 rounded-xl bg-white/5 border border-white/10 text-xs text-white focus:outline-none focus:border-white/40 font-mono w-40"
                        />
                        <button
                          onClick={takeSnapshot}
                          disabled={isTakingSnapshot}
                          className="px-4 py-2 rounded-xl bg-white/10 border border-white/20 text-white text-xs hover:bg-white hover:text-black hover:border-white transition-all flex items-center gap-2 cursor-pointer disabled:opacity-50"
                        >
                          {isTakingSnapshot ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <ImageIcon className="w-3.5 h-3.5" />}
                          Capture
                        </button>
                        
                        <button
                          onClick={() => {
                            setShowSnapshotsList(true);
                            refreshSnapshotsList();
                          }}
                          className="px-3.5 py-2 rounded-xl bg-white/5 border border-white/5 text-xs text-slate-400 hover:text-white transition-all flex items-center gap-1 cursor-pointer font-mono"
                        >
                          Library ({snapshots.length})
                        </button>
                      </div>
                    </div>
                  )}
                </div>

                {/* Bottom Row: Analytics */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                  {/* Rendered FPS */}
                  <div className="glass-panel rounded-2xl p-4 flex flex-col gap-1">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider font-mono">Render FPS</span>
                    <div className="flex items-baseline gap-1.5 mt-1">
                      <span className="text-xl font-bold font-mono text-white">
                        {latestPayload ? latestPayload.fps.toFixed(1) : '0.0'}
                      </span>
                      <span className="text-[10px] text-slate-500 font-mono">fps</span>
                    </div>
                  </div>

                  {/* E2E Latency */}
                  <div className="glass-panel rounded-2xl p-4 flex flex-col gap-1">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider font-mono">Process Latency</span>
                    <div className="flex items-baseline gap-1.5 mt-1">
                      <span className="text-xl font-bold font-mono text-white">
                        {latestPayload ? latestPayload.processing_ms.toFixed(1) : '0.0'}
                      </span>
                      <span className="text-[10px] text-slate-500 font-mono">ms</span>
                    </div>
                  </div>

                  {/* Frames Processed */}
                  <div className="glass-panel rounded-2xl p-4 flex flex-col gap-1">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider font-mono">Total Processed</span>
                    <div className="flex items-baseline gap-1.5 mt-1">
                      <span className="text-xl font-bold font-mono text-white">
                        {sessionStats.frames_processed}
                      </span>
                      <span className="text-[10px] text-slate-500 font-mono">frames</span>
                    </div>
                  </div>

                  {/* Frames Dropped */}
                  <div className="glass-panel rounded-2xl p-4 flex flex-col gap-1">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider font-mono">Dropped (Backpressure)</span>
                    <div className="flex items-baseline gap-1.5 mt-1">
                      <span className={`text-xl font-bold font-mono ${sessionStats.frames_dropped > 0 ? 'text-amber-500' : 'text-white'}`}>
                        {sessionStats.frames_dropped}
                      </span>
                      <span className="text-[10px] text-slate-500 font-mono">frames</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Hidden Canvas for capturing */}
            <canvas ref={canvasRef} className="hidden" />

            {/* Snapshot Library Slide-over Modal */}
            <AnimatePresence>
              {showSnapshotsList && (
                <>
                  {/* Backdrop */}
                  <motion.div 
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 0.6 }}
                    exit={{ opacity: 0 }}
                    onClick={() => setShowSnapshotsList(false)}
                    className="fixed inset-0 bg-black z-30 pointer-events-auto"
                  />
                  
                  {/* Content Container */}
                  <motion.div 
                    initial={{ x: '100%' }}
                    animate={{ x: 0 }}
                    exit={{ x: '100%' }}
                    transition={{ type: 'spring', damping: 25, stiffness: 220 }}
                    className="fixed right-0 top-0 bottom-0 w-full sm:w-[480px] bg-[#070707] border-l border-white/5 z-40 p-6 flex flex-col shadow-2xl overflow-hidden"
                  >
                    <div className="flex items-center justify-between border-b border-white/5 pb-4 mb-6">
                      <h3 className="text-sm font-semibold tracking-wider font-mono uppercase text-white flex items-center gap-2">
                        <ImageIcon className="w-4 h-4 text-white/80" />
                        Persisted Snapshots
                      </h3>
                      <button 
                        onClick={() => setShowSnapshotsList(false)}
                        className="text-xs text-slate-400 hover:text-white font-mono cursor-pointer"
                      >
                        CLOSE [X]
                      </button>
                    </div>

                    {/* Snapshots Grid */}
                    <div className="flex-1 overflow-y-auto flex flex-col gap-4 pr-2">
                      {snapshots.length === 0 ? (
                        <div className="flex flex-col items-center justify-center py-20 text-slate-600 gap-2">
                          <ImageIcon className="w-8 h-8 text-slate-700" />
                          <span className="text-xs font-mono font-bold tracking-wider uppercase">Library Empty</span>
                        </div>
                      ) : (
                        snapshots.map((snap) => (
                          <div 
                            key={snap.snapshot_id}
                            className="glass-card rounded-xl p-4 flex flex-col gap-3 hover:border-white/20 transition-all group"
                          >
                            <div className="flex items-start justify-between">
                              <div>
                                <h4 className="text-xs font-semibold text-slate-200 font-mono">{snap.label || 'Unnamed Snapshot'}</h4>
                                <span className="text-[9px] text-slate-500 font-mono">
                                  {new Date(snap.timestamp).toLocaleString()}
                                </span>
                              </div>
                              
                              <span className="text-[9px] px-2 py-0.5 rounded bg-white/5 border border-white/5 font-mono text-white/80">
                                {snap.theme_id}
                              </span>
                            </div>

                            <div className="flex justify-between items-center text-[10px] font-mono text-slate-500 border-t border-white/2 pt-2.5">
                              <span>Dimensions: {snap.ascii_width}x{snap.ascii_height}</span>
                              
                              <div className="flex gap-2">
                                <button
                                  onClick={async () => {
                                    try {
                                      const detail = await getSnapshot(snap.snapshot_id);
                                      setSelectedSnapshot(detail);
                                    } catch (err) {
                                      console.error(err);
                                    }
                                  }}
                                  className="text-white/80 hover:text-white font-bold uppercase cursor-pointer"
                                >
                                  View
                                </button>
                              </div>
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  </motion.div>
                </>
              )}
            </AnimatePresence>

            {/* Snapshot Detail View Modal */}
            <AnimatePresence>
              {selectedSnapshot && (
                <>
                  <motion.div 
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 0.8 }}
                    exit={{ opacity: 0 }}
                    onClick={() => setSelectedSnapshot(null)}
                    className="fixed inset-0 bg-black z-50 pointer-events-auto"
                  />
                  
                  <motion.div 
                    initial={{ opacity: 0, scale: 0.95, y: 15 }}
                    animate={{ opacity: 1, scale: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.95, y: 15 }}
                    className="fixed inset-6 sm:inset-12 bg-[#070707] border border-white/5 z-[60] rounded-3xl p-6 flex flex-col shadow-2xl overflow-hidden font-mono"
                  >
                    {/* Header */}
                    <div className="flex items-center justify-between border-b border-white/5 pb-4 mb-4">
                      <div>
                        <h3 className="text-sm font-semibold text-white">{selectedSnapshot.label}</h3>
                        <span className="text-[10px] text-slate-500">
                          {new Date(selectedSnapshot.timestamp).toLocaleString()} | Theme: {selectedSnapshot.theme_id}
                        </span>
                      </div>
                      
                      <div className="flex items-center gap-3">
                        <button
                          onClick={() => copyToClipboard(selectedSnapshot.ascii_text)}
                          className="px-3 py-1.5 rounded-lg bg-white/5 border border-white/5 text-[10px] text-slate-300 hover:text-white transition-all flex items-center gap-1 cursor-pointer"
                        >
                          <Copy className="w-3 h-3" /> Copy Text
                        </button>
                        
                        {selectedSnapshot.html_colored_ascii && (
                          <button
                            onClick={() => downloadHtml(selectedSnapshot.html_colored_ascii, selectedSnapshot.label)}
                            className="px-3 py-1.5 rounded-lg bg-white/5 border border-white/5 text-[10px] text-slate-300 hover:text-white transition-all flex items-center gap-1 cursor-pointer"
                          >
                            <Download className="w-3 h-3" /> Download HTML
                          </button>
                        )}

                        <button 
                          onClick={() => setSelectedSnapshot(null)}
                          className="px-2.5 py-1.5 rounded-lg bg-white/5 border border-white/5 text-[10px] text-slate-400 hover:text-white transition-all cursor-pointer"
                        >
                          [X] Close
                        </button>
                      </div>
                    </div>

                    {/* ASCII Display Area */}
                    <div 
                      className="flex-1 rounded-2xl overflow-auto border border-white/5 p-4 flex items-center justify-center select-all select-text"
                      style={{ 
                        backgroundColor: THEMES[selectedSnapshot.theme_id]?.bg || '#0a0a0a', 
                        color: THEMES[selectedSnapshot.theme_id]?.fg || '#fff' 
                      }}
                    >
                      {selectedSnapshot.theme_id === 'mono' ? (
                        <pre className="text-[9px] leading-[1.2] font-mono m-0 select-all p-2 select-text" style={{ whiteSpace: 'pre' }}>
                          {selectedSnapshot.ascii_text}
                        </pre>
                      ) : (
                        <div 
                          dangerouslySetInnerHTML={{ __html: selectedSnapshot.html_colored_ascii }}
                          className="m-0 overflow-visible text-[9px] select-all select-text"
                        />
                      )}
                    </div>
                  </motion.div>
                </>
              )}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>

    </div>
  );
}

export default App;
