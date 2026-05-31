#pragma once

#include <ntddk.h>
#include <wdf.h>
#include <vhf.h>

#include "hid_descriptors.h"

// {A5DCBF10-6530-11D2-901F-00C04FB951ED} — custom device interface GUID
DEFINE_GUID(GUID_DEVINTERFACE_QA_HID_COMPANION,
    0xa5dcbf10, 0x6530, 0x11d2, 0x90, 0x1f, 0x00, 0xc0, 0x4f, 0xb9, 0x51, 0xed);

// Device context — holds both VHF handles
typedef struct _DEVICE_CONTEXT {
    VHFHANDLE hVhfKeyboard;
    VHFHANDLE hVhfMouse;
} DEVICE_CONTEXT, *PDEVICE_CONTEXT;

WDF_DECLARE_CONTEXT_TYPE_WITH_NAME(DEVICE_CONTEXT, DeviceGetContext)

// Forward declarations
DRIVER_INITIALIZE DriverEntry;
EVT_WDF_DRIVER_DEVICE_ADD DeviceAdd;
EVT_WDF_IO_QUEUE_IO_WRITE EvtIoWrite;
EVT_WDF_DEVICE_CONTEXT_CLEANUP EvtDeviceCleanup;
