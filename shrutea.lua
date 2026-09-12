-- shrutea.lua
-- Analyze a rendered vocal WAV with drift.py and mark notes that are out of tune.
-- Keep drift.py next to this script (or change DRIFT_SCRIPT below).

local function script_directory()
  local source = debug.getinfo(1, "S").source
  return source:match("^@(.+[\\/])") or ""
end

local DRIFT_SCRIPT = script_directory() .. "drift.py"

local function shell_quote(value)
  -- Quote a path for the platform shell. The common Lua/Reaper builds use either
  -- Windows cmd.exe or a POSIX shell.
  if package.config:sub(1, 1) == "\\" then
    return '"' .. value:gsub('"', '\\"') .. '"'
  end
  return "'" .. value:gsub("'", "'\\\"'\\\"'") .. "'"
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

-- GetUserFileNameForRead opens REAPER's file picker and returns the chosen WAV path.
local selected, wav_path = reaper.GetUserFileNameForRead("", "Select rendered vocal WAV", ".wav")
if not selected then
  console("Shrutea: cancelled.")
  return
end

local output_path = os.tmpname() .. ".json"
local command = "python3 " .. shell_quote(DRIFT_SCRIPT) .. " " .. shell_quote(wav_path) .. " > " .. shell_quote(output_path)
local ok = os.execute(command)
if not (ok == true or ok == 0) then
  os.remove(output_path)
  console("Shrutea: drift.py failed. Confirm Python 3 and " .. DRIFT_SCRIPT .. " are available.")
  return
end

local file = io.open(output_path, "r")
local json_text = file and file:read("*a")
if file then file:close() end
os.remove(output_path)
if not json_text or json_text == "" then
  console("Shrutea: drift.py produced no JSON output.")
  return
end

local decoded_ok, results = pcall(decode_json, json_text)
if not decoded_ok then
  console("Shrutea: could not parse drift.py JSON: " .. tostring(results))
  return
end

-- Permit either a top-level array or an object containing an entries/results array.
local entries = type(results) == "table" and (results.entries or results.results or results)
if type(entries) ~= "table" then
  console("Shrutea: JSON must contain an array of pitch entries.")
  return
end

local markers_added = 0
for _, entry in ipairs(entries) do
  local cents_off = tonumber(entry.cents_off)
  local timestamp = tonumber(entry.timestamp or entry.time or entry.time_seconds)
  local note_name = entry.actual_note or entry.expected_note or entry.note_name or entry.note or "Unknown note"
  if cents_off and timestamp and cents_off > 20 then
    local label = string.format("%s: %.1f cents off", tostring(note_name), cents_off)
    -- AddProjectMarker2 adds a non-region marker to the current project at timestamp.
    reaper.AddProjectMarker2(0, false, timestamp, 0, label, -1, 0)
    markers_added = markers_added + 1
  end
end

console(string.format("Shrutea: added %d marker(s) for notes more than 20 cents off.", markers_added))
