# 🔧 Fix Network Security Group Configuration

## Current Configuration (WRONG ❌)

You have:
- **Source Type:** Network Security Group (NSG) ❌
- **Source NSG:** (empty)
- **Destination Port Range:** 80 ✅

## Correct Configuration (RIGHT ✅)

### Step 1: Change Source Type

Change **"Source Type"** from:
- ❌ **Network Security Group (NSG)**

To:
- ✅ **CIDR**

### Step 2: Set Source CIDR

After changing to CIDR, you'll see a new field:
- **Source CIDR:** `0.0.0.0/0` (allows from anywhere)

### Step 3: Complete Configuration

**Final settings should be:**
- **Stateless:** No (leave unchecked)
- **Direction:** Ingress ✅
- **Source Type:** CIDR ✅
- **Source CIDR:** `0.0.0.0/0` ✅
- **IP Protocol:** TCP ✅
- **Source Port Range:** All (or leave empty)
- **Destination Port Range:** `80` ✅
- **Description:** Allow HTTP access ✅

### Step 4: Attach NSG to Your Instance

**Important:** After creating the NSG, you must attach it!

1. Go to **Compute** → **Instances**
2. Click on your instance
3. Click **"Attached VNICs"** tab
4. Click on the VNIC
5. Click **"Edit"**
6. Under **"Network Security Groups"**, select your NSG: **NSGs**
7. Click **"Save Changes"**

## Quick Reference

**Correct NSG Rule:**
```
Direction: Ingress
Source Type: CIDR
Source CIDR: 0.0.0.0/0
IP Protocol: TCP
Destination Port Range: 80
Description: Allow HTTP access
```

**Then attach NSG to your instance!**

