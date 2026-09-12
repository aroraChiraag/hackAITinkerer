-- Minimal local stand-in for the REAPER API used by shrutea.lua.
local cwd = assert(io.popen("pwd", "r"))
local root = os.getenv("SHRUTEA_TEST_ROOT") or assert(cwd:read("*l"), "could not determine working directory")
cwd:close()
if root:sub(-1) ~= "/" then root = root .. "/" end
local wav_path = root .. "test_flat.wav"

mock_reaper_state = { markers = {}, console = {} }
reaper = {}

-- Simulates REAPER's file picker by choosing the generated flat-tone fixture.
function reaper.GetUserFileNameForRead(_, _, _)
  print("[mock REAPER] selected " .. wav_path)
  return true, wav_path
end

-- Records and prints the marker that REAPER would add to its project timeline.
function reaper.AddProjectMarker2(_, is_region, position, region_end, name, wanted_index, color)
  local marker = { is_region = is_region, position = position, region_end = region_end, name = name, wanted_index = wanted_index, color = color }
  table.insert(mock_reaper_state.markers, marker)
  print(string.format("[mock REAPER] marker @ %.3fs: %s", position, name))
  return #mock_reaper_state.markers
end

-- Prints the same plain-text message that REAPER would send to its console.
function reaper.ShowConsoleMsg(message)
  table.insert(mock_reaper_state.console, message)
  io.write("[mock REAPER console] " .. message)
end

return reaper
