-- Warning: This file is more complicated than it needs to be and I apologize for that

-- This file records the various versions associated with this version of emu-coop
-- emu-coop defines multiple file formats and communication protocols; each is versioned separately

-- For any of these versions, the pattern is "MAJOR.MINOR.PATCH VARIANT" where PATCH and VARIANT are optional and VARIANT can be multiple items.
-- The compatible-version tester in util will reject anything where MAJOR or MINOR disagree, or if the "beta" variant is present on the other side but not the local side.

-- If you are making an INCOMPATIBLE unofficial variant, I recommend replacing the major or minor version with a string, like "1.SPECIAL"

version = {
	
	-- Which released version number does this have (used for basically nothing)
	-- Put your name in here as a variant or something I guess
	release = "2.0 beta6",

	-- Protocol version for new Pipe transports (Direct/Relay). Bump on wire-format break.
	protocolVersion = 1,

	-- Format/capabilities used for modes in the modes/ directory
	-- Increment this number if you change driver.lua in a way that means things are possible in a modes/ file that weren't before
	modeFormat = "1.2"

}
