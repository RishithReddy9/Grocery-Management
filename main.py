import streamlit as st
import cloudinary
import cloudinary.uploader
import libsql_client

st.set_page_config(page_title="Pantry Tracker", layout="centered")

# --- 1. CLOUD SETUP & AUTHENTICATION ---
# Configure Cloudinary
cloudinary.config(
    cloud_name=st.secrets["CLOUDINARY_CLOUD_NAME"],
    api_key=st.secrets["CLOUDINARY_API_KEY"],
    api_secret=st.secrets["CLOUDINARY_API_SECRET"]
)

# Connect to Turso Database
@st.cache_resource
def get_db_client():
    return libsql_client.create_client_sync(
        url=st.secrets["TURSO_DATABASE_URL"],
        auth_token=st.secrets["TURSO_AUTH_TOKEN"]
    )

client = get_db_client()

# Create table if it doesn't exist (Notice we use image_url instead of image_path now)
client.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        image_url TEXT NOT NULL,
        quantities TEXT DEFAULT ''
    )
""")

SIZE_OPTIONS = ["50gm", "100gm", "200gm", "250gm", "500gm", "1kg", "2kg", "5kg"]
st.title("🏡 Household Pantry Tracker")

# --- 2. STATE MANAGEMENT (CALLBACKS) ---
def add_size_variant(item_id, current_quantities_str, selected_size):
    sizes_list = [s for s in current_quantities_str.split(",") if s]
    sizes_list.append(selected_size)
    updated_str = ",".join(sizes_list)
    client.execute("UPDATE inventory SET quantities = ? WHERE id = ?", [updated_str, item_id])

def remove_size_variant(item_id, current_quantities_str, index_to_remove):
    sizes_list = [s for s in current_quantities_str.split(",") if s]
    if 0 <= index_to_remove < len(sizes_list):
        sizes_list.pop(index_to_remove)
    updated_str = ",".join(sizes_list)
    client.execute("UPDATE inventory SET quantities = ? WHERE id = ?", [updated_str, item_id])

# --- 3. SIDEBAR: ADD TO MASTER CATALOG ---
st.sidebar.header("✨ Add New Item")
new_name = st.sidebar.text_input("Item Name", placeholder="e.g., Idly Rice")
new_image = st.sidebar.file_uploader("Take/Upload Photo", type=["jpg", "jpeg", "png", "webp"])

if st.sidebar.button("Save to Cloud Catalog"):
    if new_name and new_image:
        with st.spinner("Uploading to cloud..."):
            # Upload to Cloudinary & auto-crop to 400x400 square on their servers
            upload_result = cloudinary.uploader.upload(
                new_image,
                folder="pantry_tracker",
                transformation=[{'width': 400, 'height': 400, 'crop': 'fill', 'gravity': 'center'}]
            )
            secure_image_url = upload_result['secure_url']
            
            # Save the name and Cloudinary URL to Turso
            client.execute(
                "INSERT INTO inventory (name, image_url, quantities) VALUES (?, ?, ?)",
                [new_name, secure_image_url, ""]
            )
        st.sidebar.success(f"Added {new_name}!")
        st.rerun()
    else:
        st.sidebar.error("Please provide both a name and a photo.")

# --- 4. MAIN INTERFACE ---
tab1, tab2 = st.tabs(["📋 Current Pantry Inventory", "🛒 Shopping / Refill List"])

with tab1:
    # Fetch all items from Turso
    result = client.execute("SELECT id, name, image_url, quantities FROM inventory")
    items = result.rows
    
    if not items:
        st.info("Your catalog is empty. Use the sidebar to add your first grocery item!")
    
    for i in range(0, len(items), 2):
        cols = st.columns(2)
        for j, col in enumerate(cols):
            if i + j < len(items):
                # libsql-client returns row objects, we access them by index
                item_id = items[i + j][0]
                name = items[i + j][1]
                img_url = items[i + j][2]
                qty_str = items[i + j][3] or ""
                
                active_sizes = [s for s in qty_str.split(",") if s]
                
                with col:
                    with st.container(border=True):
                        # Display image directly from the Cloudinary URL
                        st.image(img_url, use_container_width=True)
                        st.subheader(name)
                        
                        drop_col, btn_col = st.columns([2, 1])
                        with drop_col:
                            chosen_size = st.selectbox(
                                "Select Size", 
                                SIZE_OPTIONS, 
                                key=f"drop_{item_id}", 
                                label_visibility="collapsed"
                            )
                        with btn_col:
                            st.button(
                                "➕ Add", 
                                key=f"add_btn_{item_id}", 
                                on_click=add_size_variant, 
                                args=(item_id, qty_str, chosen_size)
                            )
                        
                        if active_sizes:
                            st.write("**In Stock:**")
                            for idx, size in enumerate(active_sizes):
                                tag_col, del_col = st.columns([3, 1])
                                with tag_col:
                                    st.markdown(f"📦 **{size}**")
                                with del_col:
                                    st.button(
                                        "❌", 
                                        key=f"del_{item_id}_{idx}", 
                                        on_click=remove_size_variant, 
                                        args=(item_id, qty_str, idx),
                                        help=f"Remove this {size} pack"
                                    )
                        else:
                            st.caption("⚠️ Out of stock (Added to Shopping List)")

with tab2:
    st.header("Items Needed for Refill")
    # Fetch items where quantities string is empty
    result = client.execute("SELECT name FROM inventory WHERE quantities = '' OR quantities IS NULL")
    refill_items = result.rows
    
    if refill_items:
        st.write("The following items are completely out of stock at home:")
        for item in refill_items:
            st.checkbox(f"🔴 {item[0]}", value=False, key=f"shop_{item[0]}")
    else:
        st.success("✅ Your pantry is fully stocked! No items need a refill.")