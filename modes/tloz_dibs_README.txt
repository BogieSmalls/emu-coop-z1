Z1R DIBS! (v0.3)

Overview
--------
Z1R DIBS! leverages emu-coop to pit two players head to head as they battle for 4 Triforce 
to enter Level 9. The catch? The 8 Triforce pieces go to those who claim rights on them first
(up to 4 pieces for each player so no one gets locked out of 9), hence the name DIBS!

This Lua script is compatible with any Zelda 1 Randomizer ROM and requires that Level 9 
Entry is set to at most "4 Triforces".  Beyond that, set the flags to your heart's content, 
although I do recommend Shuffle Dungeon Drops set to "off", so players can easily determine
if a Triforce piece has been picked up in a particular level.

For those want to call DIBS! on non-go-mode items, there is also a gameplay mode to add 
exclusivity to the: White Sword, Magical Sword, Boomerang, Magical Boomerang, Red Candle,
Letter, Magical Rod, Book, Red Ring, and Magical Key

Future updates may add exclusivity to items such as maps, heart containers, and bomb upgrades.


Setup
-----
1) Make sure you have a working emu-coop/Lua setup with FCEUX. (BizHawk does not appear to
work with emu-coop.)

2) Back up your index.lua file in your ..\emu-coop-1.2\modes folder. The easiest way
to do this is to rename the file index.lua.bak or something similar.

3) Copy the contents of the tloz_dibs_v0.3.zip to your ..\emu-coop-1.2\modes folder. 

4) Generate the Z1R seed for your chosen flagset, keeping in mind that Level 9 Entry has 
to be set to at most "4 triforces". 1B5tQLYqdOceXkzGCP2vdLiFghFJOv is a good flagset 
to start with. 

5) Launch the emu-coop Lua script (..\emu-coop-1.2\coop.lua) as you normally would. 
Select either:
   - "The Legend of Zelda (DIBS! - Triforce only)", or 
   - "The Legend of Zelda (DIBS! - Triforce + Exclusive Items)"

6) Enter your nickname and your opponent's nickname (under Partner nick) and click OK
to connect.

7) You should be good to go from there. GLHF!



Thanks
------
Many thanks to Andi McClure and MegMacAttack for creating emu-coop and the base Zelda 1 
modes, respectively.

Also, thanks to Fred Coughlin for creating the Zelda 1 Randomizer. Without seeing
all the fun ways to play Z1, I wouldn't have been inspired to come up with this CTF
gameplay variant.

And, thanks to Fiskbit and Tetraly for helping me make sense of the Z1 RAM+ROM maps.

Lastly, thanks to YOU for playing! Please follow me on Twitch at twitch.tv/bogiesmalls
and feel free to send me your feedback & suggestions on how to further improve this mod.

-Bogie (6/14/2021)