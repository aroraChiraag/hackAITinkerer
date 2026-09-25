-- Minimal local stand-in for the REAPER API used by shrutea.lua.
-- mock_reaper_state.wav_path and .selected_item are set by the test before each run.

mock_reaper_state = { markers = {}, console = {}, wav_path = nil, selected_item = nil }
reaper = {}

-- Simulates REAPER's file picker by choosing the generated fixture.
function reaper.GetUserFileNameForRead(_, _, _)
  print("[mock REAPER] file picker selected " .. mock_reaper_state.wav_path)
  return true, mock_reaper_state.wav_path
end

-- A selected item is { position = seconds, length = seconds, start_offset = seconds }.
function reaper.GetSelectedMediaItem(_, index)
  if index == 0 then return mock_reaper_state.selected_item end
end

function reaper.GetActiveTake(item) return item end
function reaper.TakeIsMIDI(_) return false end
function reaper.GetMediaItemTake_Source(take) return take end
function reaper.GetMediaSourceFileName(_, _) return mock_reaper_state.wav_path end

function reaper.GetMediaItemInfo_Value(item, name)
  return ({ D_POSITION = item.position, D_LENGTH = item.length })[name]
end

function reaper.GetMediaItemTakeInfo_Value(take, name)
  return ({ D_STARTOFFS = take.start_offset })[name]
end

-- Records and prints the marker that REAPER would add to its project timeline.
function reaper.AddProjectMarker2(_, is_region, position, region_end, name, wanted_index, color)
  local marker = { is_region = is_region, position = position, region_end = region_end, name = name, number = #mock_reaper_state.markers + 1, color = color }
  table.insert(mock_reaper_state.markers, marker)
  print(string.format("[mock REAPER] marker @ %.3fs: %s", position, name))
  return marker.number
end

function reaper.CountProjectMarkers(_)
  return #mock_reaper_state.markers, #mock_reaper_state.markers, 0
end

function reaper.EnumProjectMarkers(index)
  local marker = mock_reaper_state.markers[index + 1]
  return index + 1, marker.is_region, marker.position, marker.region_end, marker.name, marker.number
end

function reaper.DeleteProjectMarker(_, number, is_region)
  for index, marker in ipairs(mock_reaper_state.markers) do
    if marker.number == number and marker.is_region == is_region then
      table.remove(mock_reaper_state.markers, index)
      return true
    end
  end
  return false
end

function reaper.ColorToNative(r, g, b) return r | (g << 8) | (b << 16) end
function reaper.Undo_BeginBlock() end
function reaper.Undo_EndBlock(_, _) end
function reaper.UpdateArrange() end

-- Prints the same plain-text message that REAPER would send to its console.
function reaper.ShowConsoleMsg(message)
  table.insert(mock_reaper_state.console, message)
  io.write("[mock REAPER console] " .. message)
end

return reaper
