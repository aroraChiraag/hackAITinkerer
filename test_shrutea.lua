-- Local integration test: mock REAPER, generate a flat WAV, then run shrutea.lua.
local cwd = assert(io.popen("pwd", "r"))
local root = os.getenv("SHRUTEA_TEST_ROOT") or assert(cwd:read("*l"), "could not determine working directory")
cwd:close()
if root:sub(-1) ~= "/" then root = root .. "/" end
local wav_path = root .. "test_flat.wav"
local python_command = os.getenv("SHRUTEA_PYTHON") or "python3"

local function shell_quote(value)
  return "'" .. value:gsub("'", "'\"'\"'") .. "'"
end

-- This uses the same `python3` command that shrutea.lua uses. Run this test
-- after installing requirements.txt into the Python environment on PATH.
local fixture_command = "SHRUTEA_TEST_WAV=" .. shell_quote(wav_path) .. " " .. shell_quote(python_command) .. " -c " .. shell_quote(
  "import os; from pathlib import Path; from test_drift import write_tone; write_tone(Path(os.environ['SHRUTEA_TEST_WAV']), 427.0)"
)
local generated = os.execute(fixture_command)
assert(generated == true or generated == 0, "could not generate test_flat.wav with python3")

dofile(root .. "mock_reaper.lua")
local ran, run_error = pcall(dofile, root .. "shrutea.lua")
os.remove(wav_path)
assert(ran, "shrutea.lua failed: " .. tostring(run_error))

-- A marker proves that drift.py ran, its JSON decoded successfully, and the
-- core loop consumed the decoded entry through the mock REAPER API.
assert(#mock_reaper_state.markers == 1, "expected one drift marker")
local marker = mock_reaper_state.markers[1]
assert(marker.name:match("G#4: 50%.0 cents off"), "unexpected marker label: " .. marker.name)
assert(#mock_reaper_state.console == 1, "expected one console summary")
assert(mock_reaper_state.console[1]:match("added 1 marker"), "unexpected console output")

print("[mock verification] Python subprocess, JSON decoding, marker, and console output passed.")
