// ============================================================================
// SUPABASE CLIENT & AUTHENTICATION
// ============================================================================

// Configuration - Replace with your actual values
const SUPABASE_CONFIG = {
    url: 'https://klciragqwcaqjwqdjsua.supabase.co',
    anonKey: 'sb_publishable_Y170peFBybdDwO3WW2yYJA_KJ6DL3ZU'
};

// Initialize Supabase client
const { createClient } = supabase;
const supabaseClient = createClient(SUPABASE_CONFIG.url, SUPABASE_CONFIG.anonKey);

// State
let currentUser = null;
let userProfile = null;
let userDesigns = [];

// ============================================================================
// AUTHENTICATION FUNCTIONS
// ============================================================================

/**
 * Initialize authentication system
 */
async function initAuth() {
    try {
        // Check for existing session
        const { data: { session } } = await supabaseClient.auth.getSession();
        if (session) {
            currentUser = session.user;
            await loadUserProfile();
            await loadUserDesigns();
            updateUIForLoggedInUser();
        }
        
        // Listen for auth state changes
        supabaseClient.auth.onAuthStateChange(async (event, session) => {
            console.log('Auth event:', event);
            currentUser = session?.user || null;
            
            if (currentUser) {
                await loadUserProfile();
                await loadUserDesigns();
                updateUIForLoggedInUser();
            } else {
                userProfile = null;
                userDesigns = [];
                updateUIForLoggedOutUser();
            }
        });
        
        console.log('✅ Auth initialized');
    } catch (error) {
        console.error('❌ Auth initialization failed:', error);
    }
}

/**
 * Sign up with email and password
 */
async function signUp(email, password, fullName) {
    try {
        const { data, error } = await supabaseClient.auth.signUp({
            email,
            password,
            options: {
                data: {
                    full_name: fullName
                }
            }
        });
        
        if (error) throw error;
        
        return { success: true, data };
    } catch (error) {
        console.error('Signup error:', error);
        return { success: false, error: error.message };
    }
}

/**
 * Sign in with email and password
 */
async function signIn(email, password) {
    try {
        const { data, error } = await supabaseClient.auth.signInWithPassword({
            email,
            password
        });
        
        if (error) throw error;
        
        return { success: true, data };
    } catch (error) {
        console.error('Sign in error:', error);
        return { success: false, error: error.message };
    }
}

/**
 * Sign in with magic link (passwordless)
 */
async function signInWithMagicLink(email) {
    try {
        const { data, error } = await supabaseClient.auth.signInWithOtp({
            email,
            options: {
                emailRedirectTo: window.location.origin
            }
        });
        
        if (error) throw error;
        
        return { success: true, data };
    } catch (error) {
        console.error('Magic link error:', error);
        return { success: false, error: error.message };
    }
}

/**
 * Sign in with OAuth provider (Google, GitHub, etc.)
 */
async function signInWithOAuth(provider) {
    try {
        const { data, error } = await supabaseClient.auth.signInWithOAuth({
            provider,
            options: {
                redirectTo: window.location.origin
            }
        });
        
        if (error) throw error;
        
        return { success: true, data };
    } catch (error) {
        console.error('OAuth error:', error);
        return { success: false, error: error.message };
    }
}

/**
 * Sign out
 */
async function signOut() {
    try {
        const { error } = await supabaseClient.auth.signOut();
        if (error) throw error;
        
        return { success: true };
    } catch (error) {
        console.error('Sign out error:', error);
        return { success: false, error: error.message };
    }
}

/**
 * Reset password
 */
async function resetPassword(email) {
    try {
        const { data, error } = await supabaseClient.auth.resetPasswordForEmail(email, {
            redirectTo: `${window.location.origin}/reset-password`
        });
        
        if (error) throw error;
        
        return { success: true, data };
    } catch (error) {
        console.error('Password reset error:', error);
        return { success: false, error: error.message };
    }
}

// ============================================================================
// USER PROFILE FUNCTIONS
// ============================================================================

/**
 * Load user profile from database
 */
async function loadUserProfile() {
    if (!currentUser) return null;
    
    try {
        const { data, error } = await supabaseClient
            .from('profiles')
            .select('*')
            .eq('id', currentUser.id)
            .single();
        
        if (error) throw error;
        
        userProfile = data;
        return data;
    } catch (error) {
        console.error('Error loading profile:', error);
        return null;
    }
}

/**
 * Update user profile
 */
async function updateUserProfile(updates) {
    if (!currentUser) return { success: false, error: 'Not authenticated' };
    
    try {
        const { data, error } = await supabaseClient
            .from('profiles')
            .update(updates)
            .eq('id', currentUser.id)
            .select()
            .single();
        
        if (error) throw error;
        
        userProfile = data;
        return { success: true, data };
    } catch (error) {
        console.error('Error updating profile:', error);
        return { success: false, error: error.message };
    }
}

/**
 * Check if user is on Pro plan
 */
function isProUser() {
    if (!userProfile) return false;
    
    if (userProfile.subscription_tier !== 'pro') return false;
    
    // Check if subscription is still valid
    if (userProfile.subscription_expires_at) {
        const expiresAt = new Date(userProfile.subscription_expires_at);
        if (expiresAt < new Date()) return false;
    }
    
    return true;
}

/**
 * Check if user can save more designs (freemium limit)
 */
function canSaveDesign() {
    if (!currentUser) return false;
    if (isProUser()) return true;
    
    // Free users can save up to 3 designs
    return userProfile.design_count < 3;
}

// ============================================================================
// DESIGN MANAGEMENT FUNCTIONS
// ============================================================================

/**
 * Load all user designs
 */
async function loadUserDesigns() {
    if (!currentUser) return [];
    
    try {
        const { data, error } = await supabaseClient
            .from('designs')
            .select('*')
            .eq('user_id', currentUser.id)
            .order('created_at', { ascending: false });
        
        if (error) throw error;
        
        userDesigns = data;
        return data;
    } catch (error) {
        console.error('Error loading designs:', error);
        return [];
    }
}

/**
 * Save a design
 */
async function saveDesign(designData) {
    if (!currentUser) {
        return { success: false, error: 'Please sign in to save designs' };
    }
    
    if (!canSaveDesign()) {
        return { 
            success: false, 
            error: 'Free users can save up to 3 designs. Upgrade to Pro for unlimited saves!',
            needsUpgrade: true
        };
    }
    
    try {
        const { data, error } = await supabaseClient
            .from('designs')
            .insert([{
                user_id: currentUser.id,
                name: designData.name,
                image_data: designData.imageData,
                canvas_image: designData.canvasImage,
                parameters: designData.parameters,
                sequence: designData.sequence,
                pattern_info: designData.patternInfo
            }])
            .select()
            .single();
        
        if (error) throw error;
        
        // Reload designs and profile
        await loadUserDesigns();
        await loadUserProfile();
        
        return { success: true, data };
    } catch (error) {
        console.error('Error saving design:', error);
        return { success: false, error: error.message };
    }
}

/**
 * Update an existing design
 */
async function updateDesign(designId, updates) {
    if (!currentUser) {
        return { success: false, error: 'Not authenticated' };
    }
    
    try {
        const { data, error } = await supabaseClient
            .from('designs')
            .update(updates)
            .eq('id', designId)
            .eq('user_id', currentUser.id) // Ensure user owns this design
            .select()
            .single();
        
        if (error) throw error;
        
        await loadUserDesigns();
        
        return { success: true, data };
    } catch (error) {
        console.error('Error updating design:', error);
        return { success: false, error: error.message };
    }
}

/**
 * Delete a design
 */
async function deleteDesign(designId) {
    if (!currentUser) {
        return { success: false, error: 'Not authenticated' };
    }
    
    try {
        const { error } = await supabaseClient
            .from('designs')
            .delete()
            .eq('id', designId)
            .eq('user_id', currentUser.id);
        
        if (error) throw error;
        
        await loadUserDesigns();
        await loadUserProfile();
        
        return { success: true };
    } catch (error) {
        console.error('Error deleting design:', error);
        return { success: false, error: error.message };
    }
}

/**
 * Load a specific design
 */
async function loadDesign(designId) {
    if (!currentUser) {
        return { success: false, error: 'Not authenticated' };
    }
    
    try {
        const { data, error } = await supabaseClient
            .from('designs')
            .select('*')
            .eq('id', designId)
            .eq('user_id', currentUser.id)
            .single();
        
        if (error) throw error;
        
        return { success: true, data };
    } catch (error) {
        console.error('Error loading design:', error);
        return { success: false, error: error.message };
    }
}

// ============================================================================
// UI UPDATE FUNCTIONS (to be implemented in main app)
// ============================================================================

/**
 * Update UI when user is logged in
 * This will be customized in index.html
 */
function updateUIForLoggedInUser() {
    console.log('User logged in:', currentUser.email);
    
    // Dispatch custom event that index.html can listen to
    window.dispatchEvent(new CustomEvent('userLoggedIn', { 
        detail: { user: currentUser, profile: userProfile } 
    }));
}

/**
 * Update UI when user is logged out
 * This will be customized in index.html
 */
function updateUIForLoggedOutUser() {
    console.log('User logged out');
    
    // Dispatch custom event that index.html can listen to
    window.dispatchEvent(new CustomEvent('userLoggedOut'));
}

// ============================================================================
// INITIALIZATION
// ============================================================================

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAuth);
} else {
    initAuth();
}

// Export functions for use in main app
window.SupabaseAuth = {
    // Auth
    signUp,
    signIn,
    signInWithMagicLink,
    signInWithOAuth,
    signOut,
    resetPassword,
    
    // Profile
    loadUserProfile,
    updateUserProfile,
    isProUser,
    canSaveDesign,
    
    // Designs
    loadUserDesigns,
    saveDesign,
    updateDesign,
    deleteDesign,
    loadDesign,
    
    // State getters
    getCurrentUser: () => currentUser,
    getUserProfile: () => userProfile,
    getUserDesigns: () => userDesigns
};