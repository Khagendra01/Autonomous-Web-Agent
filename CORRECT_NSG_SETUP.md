# ✅ Correct NSG Setup Steps

## What You're Creating

**Network Security Group Name:** NSGs ✅

## Step-by-Step Configuration

### 1. Basic Information (You've Done This ✅)
- Name: NSGs
- Compartment: realkhagendra (root)

### 2. Add Security Rule - CORRECT VALUES

**Change these settings:**

#### Current (WRONG):
- Source Type: **Network Security Group (NSG)** ❌

#### Change To (CORRECT):
- Source Type: **CIDR** ✅

**Then fill in:**
- **Source CIDR:** `0.0.0.0/0` (this allows from anywhere)
- **IP Protocol:** TCP ✅
- **Source Port Range:** All (or leave empty)
- **Destination Port Range:** `80` ✅
- **Description:** Allow HTTP access

### 3. Complete Rule Configuration

**Final rule should look like:**
```
Stateless: No (unchecked)
Direction: Ingress
Source Type: CIDR
Source CIDR: 0.0.0.0/0
IP Protocol: TCP
Source Port Range: All
Destination Port Range: 80
Description: Allow HTTP access
```

### 4. Click "Create Network Security Group"

### 5. ATTACH NSG TO YOUR INSTANCE (CRITICAL!)

After creating the NSG, you MUST attach it:

1. **Go to:** Compute → Instances
2. **Click:** Your instance
3. **Click:** "Attached VNICs" tab
4. **Click:** The VNIC (usually shows as "Primary VNIC")
5. **Click:** "Edit" button
6. **Scroll down** to "Network Security Groups"
7. **Click:** "Select a network security group"
8. **Select:** NSGs (the one you just created)
9. **Click:** "Save Changes"

## Why This Matters

- **Security Lists** = First firewall layer (already configured ✅)
- **Network Security Groups** = Second firewall layer (needs to be attached!)

**Both must allow port 80 for external access to work!**

## Test After Setup

1. Wait 1-2 minutes for changes to propagate
2. Open: http://129.80.169.184
3. Should see the web interface!

## Summary

✅ **Create NSG with:**
- Source Type: CIDR (not NSG!)
- Source CIDR: 0.0.0.0/0
- Destination Port: 80

✅ **Then attach NSG to your instance!**

