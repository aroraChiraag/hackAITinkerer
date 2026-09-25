-- Local integration test: mock REAPER, generate a flat WAV, then run shrutea.lua.
-- Run with any Lua 5.3+ interpreter from any directory: lua test_shrutea.lua
local IS_WINDOWS = package.config:sub(1, 1) == "\\"
local root = debug.getinfo(1, "S").source:match("^@(.+[\\/])") or "./"
local wav_path = root .. "test_flat.wav"

local function file_exists(path)
  local handle = io.open(path, "r")
  if handle then handle:close() end
  return handle ~= nil
end

local function quote(value)
  return IS_WINDOWS and ('"' .. value .. '"') or ("'" .. value:gsub("'", "'\"'\"'") .. "'")
end

-- Use the same interpreter that shrutea.lua picks: SHRUTEA_PYTHON, .venv, then PATH.
local python = os.getenv("SHRUTEA_PYTHON")
  or (IS_WINDOWS and root .. ".venv\\Scripts\\python.exe" or root .. ".venv/bin/python")
if not file_exists(python) and not os.getenv("SHRUTEA_PYTHON") then
  python = IS_WINDOWS and "python" or "python3"
end

-- 427 Hz sits 48 cents sharp of G#4, so auto mode flags exactly one note.
local fixture_command = quote(python)
  .. ' -c "import sys; sys.path.insert(0, sys.argv[1]); from pathlib import Path; from test_drift import write_tone; write_tone(Path(sys.argv[2]), 427.0)" '
  .. quote(root:sub(1, -2)) .. " " .. quote(wav_path)
if IS_WINDOWS then fixture_command = '"' .. fixture_command .. '"' end
local generated = os.execute(fixture_command)
assert(generated == true or generated == 0, "could not generate test_flat.wav with " .. python)

dofile(root .. "mock_reaper.lua")
mock_reaper_state.wav_path = wav_path

local function run_shrutea()
  mock_reaper_state.console = {}
  local ran, run_error = pcall(dofile, root .. "shrutea.lua")
  assert(ran, "shrutea.lua failed: " .. tostring(run_error))
end

local function shrutea_markers()
  local found = {}
  for _, marker in ipairs(mock_reaper_state.markers) do
    if marker.name:match("^ShruTea: ") then table.insert(found, marker) end
  end
  return found
end

local ok, failure = pcall(function()
  -- 1. No selected item: the file picker path places markers from project start.
  reaper.AddProjectMarker2(0, false, 1.0, 0, "Chorus", -1, 0)
  reaper.AddProjectMarker2(0, false, 2.0, 0, "ShruTea: stale marker from an earlier run", -1, 0)
  run_shrutea()
  local markers = shrutea_markers()
  assert(#markers == 1, "expected one drift marker, got " .. #markers)
  assert(markers[1].name:match("^ShruTea: G#4: 48%.%d cents sharp$"), "unexpected marker label: " .. markers[1].name)
  assert(markers[1].position < 0.1, "file-picker marker should sit near 0s")
  assert(#mock_reaper_state.markers == 2, "user markers must be kept and stale ShruTea markers removed")
  assert(#mock_reaper_state.console == 3, "expected analyzing, marker, and coaching console lines")
  assert(mock_reaper_state.console[2]:match("added 1 marker"), "unexpected console output")
  assert(mock_reaper_state.console[3]:match("ShruTea says:"), "expected labeled coaching verdict")

  -- 2. Selected item at 10s: markers follow the item on the timeline, and a
  -- re-run replaces rather than duplicates the previous ShruTea marker.
  mock_reaper_state.selected_item = { position = 10.0, length = 3.0, start_offset = 0.0 }
  run_shrutea()
  markers = shrutea_markers()
  assert(#markers == 1, "re-running must replace earlier ShruTea markers")
  assert(markers[1].position >= 10.0 and markers[1].position < 10.1, "marker should follow the selected item")
end)
os.remove(wav_path)
assert(ok, failure)

print("[mock verification] Python subprocess, JSON decoding, markers, item offset, and coaching output passed.")
