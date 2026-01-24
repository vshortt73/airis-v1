// Iris Phoneme Sprite Sheet Mapping
// Grid: 4x4, each sprite 512x512, total 2048x2048

// Sprite coordinates (x, y, width, height)
const visemeCoords = {
    "closed": { x: 0, y: 0, w: 512, h: 512 },           // Row 0, Col 0: B, M, P
    "wide_open": { x: 512, y: 0, w: 512, h: 512 },      // Row 0, Col 1: AA, AH
    "big_smile": { x: 1024, y: 0, w: 512, h: 512 },     // Row 0, Col 2: IY, EE
    "slight_smile": { x: 1536, y: 0, w: 512, h: 512 },  // Row 0, Col 3: EY, AY
    
    "lip_teeth": { x: 0, y: 512, w: 512, h: 512 },      // Row 1, Col 0: F, V
    "lip_teeth2": { x: 512, y: 512, w: 512, h: 512 },   // Row 1, Col 1: F, V (duplicate?)
    "tongue_teeth": { x: 1024, y: 512, w: 512, h: 512 },// Row 1, Col 2: TH, DH
    "teeth_close": { x: 1536, y: 512, w: 512, h: 512 }, // Row 1, Col 3: S, Z
    
    "rounded_fwd": { x: 0, y: 1024, w: 512, h: 512 },   // Row 2, Col 0: SH, ZH, CH, JH
    "medium_open": { x: 512, y: 1024, w: 512, h: 512 }, // Row 2, Col 1: EH, AE, AW, OY
    "rounded_back": { x: 1024, y: 1024, w: 512, h: 512 },// Row 2, Col 2: AO, AW, OY
    "small_open": { x: 1536, y: 1024, w: 512, h: 512 }, // Row 2, Col 3: IH, UH, ER
    
    "back_tongue": { x: 0, y: 1536, w: 512, h: 512 },   // Row 3, Col 0: K, G, NG, Y, HH
    "tongue_roof": { x: 512, y: 1536, w: 512, h: 512 }, // Row 3, Col 1: T, D, N, R, L
    "round_o": { x: 1024, y: 1536, w: 512, h: 512 },    // Row 3, Col 2: UW, OW, W
    "rest": { x: 1536, y: 1536, w: 512, h: 512 }        // Row 3, Col 3: silence, breath, rest
};

// Phoneme to Viseme mapping (CMU ARPAbet phonemes)
const phonemeToViseme = {
    // Consonants - Closed
    "B": "closed",
    "M": "closed",
    "P": "closed",
    
    // Vowels - Wide open
    "AA": "wide_open",  // "father"
    "AH": "wide_open",  // "hut"
    
    // Vowels - Big smile (high front)
    "IY": "big_smile",  // "see"
    "EE": "big_smile",  // alternative notation
    
    // Vowels - Slight smile (diphthongs ending high)
    "EY": "slight_smile", // "cake"
    "AY": "slight_smile", // "hide"
    
    // Consonants - Lip teeth contact
    "F": "lip_teeth",
    "V": "lip_teeth",
    
    // Consonants - Tongue between teeth
    "TH": "tongue_teeth", // "thin"
    "DH": "tongue_teeth", // "then"
    
    // Consonants - Teeth close together
    "S": "teeth_close",
    "Z": "teeth_close",
    
    // Consonants - Rounded forward/pursed
    "SH": "rounded_fwd",  // "she"
    "ZH": "rounded_fwd",  // "measure"
    "CH": "rounded_fwd",  // "church"
    "JH": "rounded_fwd",  // "jump"
    
    // Vowels - Medium open
    "EH": "medium_open",  // "bed"
    "AE": "medium_open",  // "cat"
    
    // Vowels - Rounded back
    "AO": "rounded_back", // "dog"
    "AW": "rounded_back", // "cow"
    "OY": "rounded_back", // "toy"
    
    // Vowels - Small opening
    "IH": "small_open",   // "it"
    "UH": "small_open",   // "book"
    "ER": "small_open",   // "bird"
    
    // Consonants - Back of tongue raised
    "K": "back_tongue",
    "G": "back_tongue",
    "NG": "back_tongue",  // "sing"
    "Y": "back_tongue",   // "yes"
    "HH": "back_tongue",  // "hello"
    
    // Consonants - Tongue to roof
    "T": "tongue_roof",
    "D": "tongue_roof",
    "N": "tongue_roof",
    "R": "tongue_roof",
    "L": "tongue_roof",
    
    // Vowels - Round O
    "UW": "round_o",      // "food"
    "OW": "round_o",      // "go"
    "W": "round_o",       // "we"
    
    // Special - Rest/neutral
    "SIL": "rest",        // silence
    "SP": "rest",         // short pause
    "": "rest"            // empty/default
};

// Helper function to get viseme coordinates from phoneme
function getVisemeForPhoneme(phoneme) {
    const visemeName = phonemeToViseme[phoneme.toUpperCase()] || "rest";
    return visemeCoords[visemeName];
}

// Helper function to get all phonemes for a viseme (for testing)
function getPhonemesForViseme(visemeName) {
    return Object.keys(phonemeToViseme).filter(p => phonemeToViseme[p] === visemeName);
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        visemeCoords,
        phonemeToViseme,
        getVisemeForPhoneme,
        getPhonemesForViseme
    };
}
