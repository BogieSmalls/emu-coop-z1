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
	guid = "31608316-0831-6083-1608-31608000003",
	format = "1.2",
	name = "The Legend of Zelda (DIBS! - Triforce + Exclusive Items + Entrances)",
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
local lastItemGrabRoom = 0
local lastInventoryGrab = {}

function getMemoryOffset(item)
	local nesHeaderOffset = 0x10
	local address = 0x0

	-- Entrance Room locations (L1-L6): 0x1942b, 0x19527, 0x19623, 0x1971f, 0x1981b, 0x19917
	-- Entrance Room locations (L7-L9): 0x19a13, 0x19b0f, 0x19c0b
	if (item == "L_1_Entrance") then address = (0x1942b + nesHeaderOffset) end 
	if (item == "L_2_Entrance") then address = (0x19527 + nesHeaderOffset) end 
	if (item == "L_3_Entrance") then address = (0x19623 + nesHeaderOffset) end 
	if (item == "L_4_Entrance") then address = (0x1971f + nesHeaderOffset) end 
	if (item == "L_5_Entrance") then address = (0x1981b + nesHeaderOffset) end 
	if (item == "L_6_Entrance") then address = (0x19917 + nesHeaderOffset) end 
	if (item == "L_7_Entrance") then address = (0x19a13 + nesHeaderOffset) end 
	if (item == "L_8_Entrance") then address = (0x19b0f + nesHeaderOffset) end 
	if (item == "L_9_Entrance") then address = (0x19c0b + nesHeaderOffset) end 
	
	-- Triforce Room locations (L1-L6): 0x1942c, 0x19528, 0x19624, 0x19720, 0x1981c, 0x19918
	-- Triforce Room locations (L7-L8): 0x19a14, 0x19b10
	if (item == "L_1_Triforce") then address = (0x1942c + nesHeaderOffset) end 
	if (item == "L_2_Triforce") then address = (0x19528 + nesHeaderOffset) end 
	if (item == "L_3_Triforce") then address = (0x19624 + nesHeaderOffset) end 
	if (item == "L_4_Triforce") then address = (0x19720 + nesHeaderOffset) end 
	if (item == "L_5_Triforce") then address = (0x1981c + nesHeaderOffset) end 
	if (item == "L_6_Triforce") then address = (0x19918 + nesHeaderOffset) end 
	if (item == "L_7_Triforce") then address = (0x19a14 + nesHeaderOffset) end 
	if (item == "L_8_Triforce") then address = (0x19b10 + nesHeaderOffset) end 

	return address
end


local playerEntrance = {
	-- 0x06ff + L_X value = L_X memory address (1-6)
	-- 0x077f + L_X value = L_X memory address (7-9)

	Level_1 = tonumber(0x06ff + rom.readbyte(getMemoryOffset("L_1_Entrance")), 10),
	Level_2 = tonumber(0x06ff + rom.readbyte(getMemoryOffset("L_2_Entrance")), 10),
	Level_3 = tonumber(0x06ff + rom.readbyte(getMemoryOffset("L_3_Entrance")), 10),
	Level_4 = tonumber(0x06ff + rom.readbyte(getMemoryOffset("L_4_Entrance")), 10),
	Level_5 = tonumber(0x06ff + rom.readbyte(getMemoryOffset("L_5_Entrance")), 10),
	Level_6 = tonumber(0x06ff + rom.readbyte(getMemoryOffset("L_6_Entrance")), 10),
	Level_7 = tonumber(0x077f + rom.readbyte(getMemoryOffset("L_7_Entrance")), 10),
	Level_8 = tonumber(0x077f + rom.readbyte(getMemoryOffset("L_8_Entrance")), 10),
	Level_9 = tonumber(0x077f + rom.readbyte(getMemoryOffset("L_9_Entrance")), 10),
}


local playerTriforce = {
	-- 0x06ff + L_X value = L_X memory address (1-6)
	-- 0x077f + L_X value = L_X memory address (7-8)

	Level_1_Triforce = tonumber(0x06ff + rom.readbyte(getMemoryOffset("L_1_Triforce")), 10),
	Level_2_Triforce = tonumber(0x06ff + rom.readbyte(getMemoryOffset("L_2_Triforce")), 10),
	Level_3_Triforce = tonumber(0x06ff + rom.readbyte(getMemoryOffset("L_3_Triforce")), 10),
	Level_4_Triforce = tonumber(0x06ff + rom.readbyte(getMemoryOffset("L_4_Triforce")), 10),
	Level_5_Triforce = tonumber(0x06ff + rom.readbyte(getMemoryOffset("L_5_Triforce")), 10),
	Level_6_Triforce = tonumber(0x06ff + rom.readbyte(getMemoryOffset("L_6_Triforce")), 10),
	Level_7_Triforce = tonumber(0x077f + rom.readbyte(getMemoryOffset("L_7_Triforce")), 10),
	Level_8_Triforce = tonumber(0x077f + rom.readbyte(getMemoryOffset("L_8_Triforce")), 10),
}

local exclusiveInventoryItems = {
	-- Required items: WoodSword, SilverArrows, Bow, Recorder, Raft, Ladder, PowerBracelet
	Sword = tonumber(0x0657, 10), 
	Boomerang = tonumber(0x0674, 10),
	MagicalBoomerang = tonumber(0x0675, 10),
	Candle = tonumber(0x065B, 10), 
	Letter = tonumber(0x0666, 10),
	MagicalRod = tonumber(0x065f, 10),
	Book = tonumber(0x0661, 10),
	Ring = tonumber(0x0662, 10), 
	MagicalKey = tonumber(0x0664 , 10)
	-- Compass = tonumber(0x0667, 10),
	-- Map = tonumber(0x0668, 10),
	-- L9Compass = tonumber(0x0669, 10),
	-- L9Map = tonumber(0x066A, 10),
	-- Heart Containers? 0x066F
	-- Bomb Upgrades? 0x067C
}

local exclusiveExclusions = {
	Sword = 1,  -- White and Magical Swords only
	Candle = 1, -- Red Candle only
	Ring = 1    -- Red Ring only
}

-- Monitor the inventory items to sync
for key,val in pairs(exclusiveInventoryItems) do
	spec.sync[val] = {name=key, verb="called dibs on the",
		kind=function(value, previousValue, receiving)
 			if (value ~= previousValue) then
				-- emu.print("key: ", key, " / index: ", val, " / value: ", value, " / previousValue: ", previousValue, " / receiving: ", receiving)

				lastInventoryGrab = {key, value} 
				-- emu.print("Last Inventory Grab: ", lastInventoryGrab[1], " / Value: ", lastInventoryGrab[2])
				-- check if item grab should be synced
				if (not isExcluded(lastInventoryGrab)) then
					if receiving then
						syncKey, syncValue = value:match("([^,]+),([^,]+)") -- Split "Boomerang,1752" by its comma into a key/value pair)

						if (key == syncKey) then
							memory.writebyte(syncValue, bit.bor(0x10, memory.readbyte(syncValue)))
							return true, previousValue
						end
					else
						valueToSync = key .. "," .. lastItemGrabRoom -- (format: "Boomerang,1752")
						return true, valueToSync
					end
				end
			end
		end
	}
end

-- MAP DATA:
-- OW:  0x067f, 0x06fe
-- DUN: 0x06ff, 0x07fe
-- 0x10 item collected

-- Locally monitor the last screen in the overworld and dungeons that had their item collected, with the exception of triforce rooms which are handled separately
for i = 0x067f, 0x07fe do
	spec.sync[i] = {
		kind=function(value, previousValue, receiving)
 			if (value ~= previousValue and (not receiving) and (not isInList(playerTriforce, i)) and (not isInList(playerEntrance, i))) then
 				previousValueHasItem = hasItem(previousValue)
				valueHasItem = hasItem(value)

				if (valueHasItem and (not previousValueHasItem)) then
					-- emu.print("Item grabbed in room: ", i, " / value: ", value, " / previousValue: ", previousValue, " / receiving: ", receiving)
					lastItemGrabRoom = i
				end
			end
		end
	}
end

-- Monitor dungeon entrance discovery
for key, val in pairs(playerEntrance) do
	spec.sync[val] = {name=key, verb="found",
		kind=function(value, previousValue, receiving)
 			if (value ~= previousValue) then
 				previousValueHasVisited = hasVisited(previousValue)
				valueHasVisited = hasVisited(value)

				if (valueHasVisited and (not previousValueHasVisited)) then
					if receiving then
						return true, previousValue
					else
						-- emu.print("Dungeon Entrance discovered: ", key, " / val: ", val, " / value: ", value, " / previousValue: ", previousValue, " / receiving: ", receiving)
						return true, 0x20
					end
				end
			end
		end
	}
end


-- Monitor the triforce to sync (triforce need to be handled separate of other inventory items)
for key, val in pairs(playerTriforce) do
	spec.sync[val] = {name=key, verb="called dibs on the",
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

function isExcluded(itemKVP)
	if (exclusiveExclusions[itemKVP[1]] == nil or exclusiveExclusions[itemKVP[1]] == 0) then
		return false
	else
		return exclusiveExclusions[itemKVP[1]] == itemKVP[2]
	end
end

function hasItem(itemValue)
	if (itemValue == nil) then
 		return false
	else
		return (bit.band(0x10, itemValue) == 0x10)
	end
end

function hasVisited(itemValue)
	if (itemValue == nil) then
		return false
	else
		return (bit.band(0x20, itemValue) == 0x20)
	end
end

function isInList (list, val)
    for index, value in pairs(list) do
        if value == val then
            return true
        end
    end

    return false
end

return spec