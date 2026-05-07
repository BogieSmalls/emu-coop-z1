-- STOP! Are you about to edit this file?
-- If you change ANYTHING, please please PLEASE run the following script:
-- https://www.guidgenerator.com/online-guid-generator.aspx
-- and put in a new GUID in the "guid" field.

-- Author: megmacattack 
-- CTF tweaks: Bogie (twitch.tv/bogiesmalls)
-- Thanks to: Fiskbit, Tetraly
-- Data source: mostly http://datacrystal.romhacking.net/wiki/The_Legend_of_Zelda:RAM_map
-- This file is available under Creative Commons CC0 

local spec = {
	guid = "31608316-0831-6083-1608-31608000001",
	format = "1.2",
	name = "The Legend of Zelda (DIBS! - Triforce only)",
	match = {"stringtest", addr=0xffeb, value="ZELDA"},

	running = {"test", addr = 0x12, gte = 0x4, lte = 0xD},
	sync = {},
	startup=function(forceSend)
				if forceSend then
					syncAfterCrash()
				end
			end
}

local oppTriforceCount = 0

function getMemoryOffset(item)
	local nesHeaderOffset = 0x10
	local address = 0x0

	-- Triforce Room locations (L1-L6): 0x1942c, 0x19528, 0x19624, 0x19720, 0x1981c, 0x19918
	-- Triforce Room locations (L7-L8): 0x19a14, 0x19b10
	if (item == "L_1") then address = (0x1942c + nesHeaderOffset) end 
	if (item == "L_2") then address = (0x19528 + nesHeaderOffset) end 
	if (item == "L_3") then address = (0x19624 + nesHeaderOffset) end 
	if (item == "L_4") then address = (0x19720 + nesHeaderOffset) end 
	if (item == "L_5") then address = (0x1981c + nesHeaderOffset) end 
	if (item == "L_6") then address = (0x19918 + nesHeaderOffset) end 
	if (item == "L_7") then address = (0x19a14 + nesHeaderOffset) end 
	if (item == "L_8") then address = (0x19b10 + nesHeaderOffset) end 

	return address
end


local playerTriforce = {
	-- 0x06ff + L_X value = L_X memory address
	-- 0x077f + L_X value = L_X memory address

	tonumber(0x06ff + rom.readbyte(getMemoryOffset("L_1")), 10),
	tonumber(0x06ff + rom.readbyte(getMemoryOffset("L_2")), 10),
	tonumber(0x06ff + rom.readbyte(getMemoryOffset("L_3")), 10),
	tonumber(0x06ff + rom.readbyte(getMemoryOffset("L_4")), 10),
	tonumber(0x06ff + rom.readbyte(getMemoryOffset("L_5")), 10),
	tonumber(0x06ff + rom.readbyte(getMemoryOffset("L_6")), 10),
	tonumber(0x077f + rom.readbyte(getMemoryOffset("L_7")), 10),
	tonumber(0x077f + rom.readbyte(getMemoryOffset("L_8")), 10),
}

-- Monitor the triforce to sync (triforce need to be handled separate of other inventory items)
for key, val in pairs(playerTriforce) do
	spec.sync[val] = {name="Triforce Piece", verb="called dibs on a",
		kind=function(value, previousValue, receiving)
			-- emu.print("key: ", key, " / index: ", val, " / value: ", value, " / previousValue: ", previousValue, " / receiving: ", receiving)

			-- Only send/rcv notification if value has changed
			if (value ~= previousValue) then
								
				-- Determine if previousValue and value values have the triforce bit on
				valueHasTri = hasItem(value)
 				previousValueHasTri = hasItem(previousValue)

				-- If opponent picked up triforce, process notification accordingly
				if receiving then
					if (valueHasTri and (not previousValueHasTri)) then
						oppTriforceCount = oppTriforceCount + 1
						
						-- If opponent picked up first 4 triforce pieces, process update
						if oppTriforceCount <= 4 then
							return true, bit.bor(0x10, previousValue)
						else
							return false, previousValue
						end
					end
				-- Else, send notification if triforce picked up
				else
					if (valueHasTri and (not previousValueHasTri)) then
						return true, 0x10
					end
				end
			end
		end
	}
end

-- Recalculate oppTriforceCount if restarting from a crash
function syncAfterCrash()
	-- Count of triforce picked up from the floor by both players (assuming no offline sync activity)
	floorTriforce = 0

	if (bit.band(0x10, memory.readbyte(playerTriforce[1])) == 0x10) then floorTriforce = floorTriforce + 1 end
	if (bit.band(0x10, memory.readbyte(playerTriforce[2])) == 0x10) then floorTriforce = floorTriforce + 1 end
	if (bit.band(0x10, memory.readbyte(playerTriforce[3])) == 0x10) then floorTriforce = floorTriforce + 1 end
	if (bit.band(0x10, memory.readbyte(playerTriforce[4])) == 0x10) then floorTriforce = floorTriforce + 1 end
	if (bit.band(0x10, memory.readbyte(playerTriforce[5])) == 0x10) then floorTriforce = floorTriforce + 1 end
	if (bit.band(0x10, memory.readbyte(playerTriforce[6])) == 0x10) then floorTriforce = floorTriforce + 1 end
	if (bit.band(0x10, memory.readbyte(playerTriforce[7])) == 0x10) then floorTriforce = floorTriforce + 1 end
	if (bit.band(0x10, memory.readbyte(playerTriforce[8])) == 0x10) then floorTriforce = floorTriforce + 1 end

	-- Count of triforce in player's inventory
	inventoryTri = sum(toBits(memory.readbyte(0x0671), 8))

	oppTriforceCount = (floorTriforce - inventoryTri)
	emu.print("Post-Crash Opponent Triforce Count: ", oppTriforceCount)
end

-- Helper function to convert inventory triforce byte to bits
function toBits(num, bits)
    -- returns a table of bits
    local t={} -- will contain the bits
    for b=bits,1,-1 do
        rest=math.fmod(num,2)
        t[b]=rest
        num=(num-rest)/2
    end
    if num==0 then return t else return {'Not enough bits to represent this number'} end
end

-- Helper function to count the number of inventory triforce bits
function sum(t)
    local sum = 0
    for k,v in pairs(t) do
        sum = sum + v
    end

    return sum
end

function hasItem(itemValue)
	if (itemValue == nil) then
 		return false
	else
		return (bit.band(0x10, itemValue) == 0x10)
	end
end

return spec