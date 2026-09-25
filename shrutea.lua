-- shrutea.lua
-- Analyze a vocal take with drift.py and mark notes that are out of tune.
-- Select the vocal item before running to analyze it in place; otherwise a
-- file picker asks for a rendered WAV that starts at the project start.
-- Keep drift.py, llm_coach.py, and commentary.py next to this script.

local IS_WINDOWS = package.config:sub(1, 1) == "\\"
local MARKER_PREFIX = "ShruTea: "

local function script_directory()
  local source = debug.getinfo(1, "S").source
  return source:match("^@(.+[\\/])") or ""
end

local function file_exists(path)
  local handle = io.open(path, "r")
  if handle then handle:close() end
  return handle ~= nil
end

local SCRIPT_DIR = script_directory()
local DRIFT_SCRIPT = os.getenv("SHRUTEA_DRIFT_SCRIPT") or (SCRIPT_DIR .. "drift.py")
local COACH_SCRIPT = os.getenv("SHRUTEA_COACH_SCRIPT") or (SCRIPT_DIR .. "llm_coach.py")
-- "auto" measures each sung note against its nearest semitone; "reference"
-- compares against REFERENCE_SEQUENCE in drift.py.
local MODE = os.getenv("SHRUTEA_MODE") or "auto"

-- Prefer SHRUTEA_PYTHON, then a .venv next to this script, then PATH. GUI
-- hosts such as REAPER often lack the terminal's PATH and environment.
local function find_python()
  local configured = os.getenv("SHRUTEA_PYTHON")
  if configured and configured ~= "" then return configured end
  local venv_python = SCRIPT_DIR .. (IS_WINDOWS and ".venv\\Scripts\\python.exe" or ".venv/bin/python")
  if file_exists(venv_python) then return venv_python end
  return IS_WINDOWS and "python" or "python3"
end

local function temp_path(suffix)
  if IS_WINDOWS then
    -- os.tmpname() can point at the drive root on Windows, which is not writable.
    local directory = os.getenv("TEMP") or os.getenv("TMP") or "."
    return string.format("%s\\shrutea_%d_%d%s", directory, os.time(), math.random(1, 1000000000), suffix)
  end
  return os.tmpname() .. suffix
end

local function shell_quote(value)
  -- Quote a path for the platform shell: Windows cmd.exe or a POSIX shell.
  if IS_WINDOWS then
    return '"' .. value:gsub('"', '\\"') .. '"'
  end
  return "'" .. value:gsub("'", "'\"'\"'") .. "'"
end

local function run(command)
  -- cmd.exe /c strips the first and last quote of a command that starts with
  -- one, so wrap the whole command in an extra pair of quotes on Windows.
  if IS_WINDOWS then command = '"' .. command .. '"' end
  local ok = os.execute(command)
  return ok == true or ok == 0
end

local function read_file(path)
  local handle = io.open(path, "r")
  if not handle then return nil end
  local text = handle:read("*a")
  handle:close()
  return text
end

-- Small, dependency-free JSON decoder for drift.py's JSON output.
local function decode_json(text)
  local position = 1

  local function whitespace()
    while text:sub(position, position):match("%s") do position = position + 1 end
  end

  local parse_value

  local function parse_string()
    position = position + 1 -- opening quote
    local pieces = {}
    while position <= #text do
      local character = text:sub(position, position)
      if character == '"' then
        position = position + 1
        return table.concat(pieces)
      elseif character == "\\" then
        local escaped = text:sub(position + 1, position + 1)
        local escapes = { ['"'] = '"', ['\\'] = '\\', ['/'] = '/', b = '\b', f = '\f', n = '\n', r = '\r', t = '\t' }
        if escaped == "u" then
          local hex = text:sub(position + 2, position + 5)
          local codepoint = tonumber(hex, 16)
          if not codepoint or #hex ~= 4 then error("invalid JSON unicode escape") end
          -- drift.py labels are normally ASCII; preserve non-ASCII BMP characters too.
          if codepoint < 128 then
            pieces[#pieces + 1] = string.char(codepoint)
          elseif codepoint < 2048 then
            pieces[#pieces + 1] = string.char(192 + math.floor(codepoint / 64), 128 + codepoint % 64)
          else
            pieces[#pieces + 1] = string.char(224 + math.floor(codepoint / 4096), 128 + math.floor(codepoint / 64) % 64, 128 + codepoint % 64)
          end
          position = position + 6
        elseif escapes[escaped] then
          pieces[#pieces + 1] = escapes[escaped]
          position = position + 2
        else
          error("invalid JSON escape")
        end
      else
        pieces[#pieces + 1] = character
        position = position + 1
      end
    end
    error("unterminated JSON string")
  end

  local function parse_array()
    position = position + 1
    local result = {}
    whitespace()
    if text:sub(position, position) == "]" then position = position + 1; return result end
    while true do
      result[#result + 1] = parse_value()
      whitespace()
      local delimiter = text:sub(position, position)
      if delimiter == "]" then position = position + 1; return result end
      if delimiter ~= "," then error("expected ',' or ']' in JSON array") end
      position = position + 1
      whitespace()
    end
  end

  local function parse_object()
    position = position + 1
    local result = {}
    whitespace()
    if text:sub(position, position) == "}" then position = position + 1; return result end
    while true do
      if text:sub(position, position) ~= '"' then error("expected JSON object key") end
      local key = parse_string()
      whitespace()
      if text:sub(position, position) ~= ":" then error("expected ':' in JSON object") end
      position = position + 1
      result[key] = parse_value()
      whitespace()
      local delimiter = text:sub(position, position)
      if delimiter == "}" then position = position + 1; return result end
      if delimiter ~= "," then error("expected ',' or '}' in JSON object") end
      position = position + 1
      whitespace()
    end
  end

  function parse_value()
    whitespace()
    local character = text:sub(position, position)
    if character == '"' then return parse_string() end
    if character == "[" then return parse_array() end
    if character == "{" then return parse_object() end
    local number_start = position
    if character == "-" then position = position + 1 end
    local integer_start = position
    while text:sub(position, position):match("%d") do position = position + 1 end
    if integer_start ~= position then
      if text:sub(position, position) == "." then
        position = position + 1
        local fraction_start = position
        while text:sub(position, position):match("%d") do position = position + 1 end
        if fraction_start == position then error("invalid JSON number") end
      end
      if text:sub(position, position):match("[eE]") then
        position = position + 1
        if text:sub(position, position):match("[-+]") then position = position + 1 end
        local exponent_start = position
        while text:sub(position, position):match("%d") do position = position + 1 end
        if exponent_start == position then error("invalid JSON exponent") end
      end
      return tonumber(text:sub(number_start, position - 1))
    end
    position = number_start
    if text:sub(position, position + 3) == "true" then position = position + 4; return true end
    if text:sub(position, position + 4) == "false" then position = position + 5; return false end
    if text:sub(position, position + 3) == "null" then position = position + 4; return nil end
    error("invalid JSON value at character " .. position)
  end

  local result = parse_value()
  whitespace()
  if position <= #text then error("trailing JSON data") end
  return result
end

local function console(message)
  -- ShowConsoleMsg writes plain text to REAPER's ReaScript console.
  reaper.ShowConsoleMsg(message .. "\n")
end

-- Returns the WAV path, the project time that the file's 0s maps to, and the
-- item span (if any) that markers must fall inside.
local function choose_take()
  local item = reaper.GetSelectedMediaItem and reaper.GetSelectedMediaItem(0, 0)
  local take = item and reaper.GetActiveTake(item)
  if take and not reaper.TakeIsMIDI(take) then
    local source = reaper.GetMediaItemTake_Source(take)
    local path = source and reaper.GetMediaSourceFileName(source, "")
    if path and path ~= "" then
      local position = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
      local length = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
      local start_offset = reaper.GetMediaItemTakeInfo_Value(take, "D_STARTOFFS")
      return path, position - start_offset, position, position + length
    end
  end
  -- GetUserFileNameForRead opens REAPER's file picker and returns the chosen WAV path.
  local selected, path = reaper.GetUserFileNameForRead("", "Select rendered vocal WAV", ".wav")
  if not selected then return nil end
  return path, 0, nil, nil
end

-- Remove markers left by an earlier ShruTea run so re-analysis never duplicates them.
local function clear_previous_markers()
  local _, marker_count, region_count = reaper.CountProjectMarkers(0)
  for index = marker_count + region_count - 1, 0, -1 do
    local _, is_region, _, _, name, number = reaper.EnumProjectMarkers(index)
    if not is_region and name:sub(1, #MARKER_PREFIX) == MARKER_PREFIX then
      reaper.DeleteProjectMarker(0, number, false)
    end
  end
end

-- Flat notes are orange and sharp notes blue; 0x1000000 marks the colour as custom.
local function marker_color(direction)
  if direction == "sharp" then return reaper.ColorToNative(70, 130, 220) | 0x1000000 end
  return reaper.ColorToNative(216, 108, 61) | 0x1000000
end

local wav_path, file_start, item_start, item_end = choose_take()
if not wav_path then
  console("ShruTea: cancelled.")
  return
end

local python = find_python()
local output_path = temp_path(".json")
local error_path = temp_path(".log")
local command = shell_quote(python) .. " " .. shell_quote(DRIFT_SCRIPT) .. " " .. shell_quote(wav_path)
  .. " --mode " .. MODE .. " > " .. shell_quote(output_path) .. " 2> " .. shell_quote(error_path)
console("ShruTea: analyzing " .. wav_path .. " (" .. MODE .. " mode)...")
local ok = run(command)
local json_text = read_file(output_path)
local error_text = read_file(error_path) or ""
os.remove(error_path)
if not ok or not json_text or not json_text:match("%S") then
  os.remove(output_path)
  console("ShruTea: drift.py failed using Python '" .. python .. "'. Set SHRUTEA_PYTHON or create .venv next to shrutea.lua.")
  if error_text:match("%S") then console(error_text) end
  return
end

local decoded_ok, results = pcall(decode_json, json_text)
if not decoded_ok then
  os.remove(output_path)
  console("ShruTea: could not parse drift.py JSON: " .. tostring(results))
  return
end

-- Permit either a top-level array or an object containing an entries/results array.
local entries = type(results) == "table" and (results.entries or results.results or results)
if type(entries) ~= "table" then
  os.remove(output_path)
  console("ShruTea: JSON must contain an array of pitch entries.")
  return
end

reaper.Undo_BeginBlock()
clear_previous_markers()
local markers_added = 0
for _, entry in ipairs(entries) do
  local cents_off = tonumber(entry.cents_off)
  local timestamp = tonumber(entry.timestamp or entry.time or entry.time_seconds)
  if cents_off and timestamp then
    local position = file_start + timestamp
    if not item_start or (position >= item_start and position < item_end) then
      local expected = entry.expected_note or entry.note or "?"
      local actual = entry.actual_note or expected
      local note_name = actual ~= expected and (expected .. " -> " .. actual) or expected
      local label = string.format("%s%s: %.1f cents %s", MARKER_PREFIX, note_name, cents_off, entry.direction or "off")
      -- AddProjectMarker2 adds a non-region marker to the current project.
      reaper.AddProjectMarker2(0, false, position, 0, label, -1, marker_color(entry.direction))
      markers_added = markers_added + 1
    end
  end
end
reaper.Undo_EndBlock("ShruTea: mark pitch drift", -1)
reaper.UpdateArrange()

console(string.format("ShruTea: added %d marker(s) for notes more than 20 cents off.", markers_added))

-- Run the context-aware coach after markers are added, then print its verdict
-- in REAPER's console. llm_coach.py reads API keys from .env and otherwise
-- returns a reliable local template verdict.
local coach_output_path = temp_path(".txt")
local coach_command = shell_quote(python) .. " " .. shell_quote(COACH_SCRIPT) .. " " .. shell_quote(output_path)
  .. " --mode " .. MODE .. " > " .. shell_quote(coach_output_path)
local coach_ok = run(coach_command)
local verdict = read_file(coach_output_path)
os.remove(output_path)
os.remove(coach_output_path)
if coach_ok and verdict and verdict:match("%S") then
  console("ShruTea says: " .. verdict:gsub("%s+$", ""))
else
  console("ShruTea says: Pitch analysis is complete; coaching verdict unavailable.")
end
