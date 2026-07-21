/**
 \file          can_aux_global.h
 \author        Alexey Evlampjev, Mikhail Kuniaev
 \date          06, 2023
 \brief         Auxiliary defines and functions for engine control system project CAN buses
 \note          Only universal for all CAN busses and all nodes defines and functions are placing 
                at this file
 */

#ifndef __can_aux_global_H_
#define __can_aux_global_H_

#ifdef __cplusplus
 extern "C" {
#endif

#pragma anon_unions

#include <stddef.h>

#if !defined (MRTK_MODULE)
     #define MRTK_MODULE
#endif


#if defined(MRTK_MODULE)
	#include "stm32f446xx.h"
	#include "stm32f4xx.h"
#elif defined(KNOCK_SENSOR_INTERFACE)
	#include "stm32f446xx.h"
	#include "stm32f4xx.h"
#elif defined(IGNITION_CONTROL_MODULE)
	#include "stm32f446xx.h"	 
	#include "stm32f4xx.h"
#elif defined(CAPASITOR_DISCHARGE_IGNITION)
	#include "stm32f103xx.h"
	#include "stm32f1xx.h"
#elif defined(VCU_MODULE)
	#include "stm32f103xb.h"
	#include "stm32f1xx.h"
#else
	#error "You must select device type"
#endif




#if !defined(CAN_ID_STD)
    #define CAN_ID_STD                  0x00000000U  /*!< Standard Id */
    #define CAN_ID_EXT                  0x00000004U  /*!< Extended Id */
#endif

#if !defined(CAN_RTR_DATA)
    #define CAN_RTR_DATA                0x00000000U  /*!< Data frame */
    #define CAN_RTR_REMOTE              0x00000002U  /*!< Remote frame */
#endif

#define CAN_STANDARD_DATA_LENGHT 8
#define CAN_TIMEOUT_FOR_CAN_TR 20

#define CAN_MAX_STDID 0x7FFU
#define CAN_MAX_EXTID 0x1FFFFFFFU


typedef uint32_t flag_t;

typedef enum
{
    KSI_NOTICE_BASE 	= 0x0000,
    KSI_GENERAL_BASE 	= 0x0100,
    KSI_SERVICE_BASE 	= 0x0200,
}	canstdid_base_t __attribute__((aligned(4)));

typedef enum
{
    PRI_LOW = 2,
    PRI_NORMAL,
    PRI_HIGH
} priority_t __attribute__((aligned(2)));



// 8-байтовый блок данных унив. формата для анализа  и преобразования
// получаемых по CAN шине данных 
typedef union
{
    uint8_t     us[8];
    uint16_t    um[4];
    uint32_t    uw[2];
    struct
    {
        union
        {
            uint8_t     us[2];
            uint16_t    um;
        } identifier;
        union
        {
            uint8_t     us[2];
            uint16_t    um;
        } code;
        union
        {
            int32_t     w;
            uint32_t    uw;
            int16_t     m[2];
            uint16_t    um[2];
            float       f;
        } value;
    };
} canmsg_data_t;

typedef union
{
    int8_t    s[4];
    uint8_t   us[4];
    int16_t   m[2];
    uint16_t  um[2];
    uint32_t  uw;
    float     f;
} box32_t;

typedef union
{
    int8_t      s[2];
    uint8_t     us[2];
    int16_t     m;
    uint16_t    um;
} box16_t;

// struct for packaging HAL structures CanTxMsgTypeDef and CanRxMsgTypeDef
// from "stm32f4xx_hal_can.h"
typedef struct 
{
    volatile uint32_t StdId;    //< statndard identifier (11 bit, 0..0x7FF)
    volatile uint32_t ExtId;    //< extended identifier (29 bit)
    volatile uint32_t IDE;      //< type of identifier
    volatile uint32_t RTR;      //< type of frame for message
    volatile uint32_t DLC;      //< data length of frame
    union
    {
        volatile uint8_t Data[8];               //< data
        volatile canmsg_data_t dataStruct;      //< 
    };
    union
    {
        volatile uint8_t padding1[4];   //< padding TxMsg to RxMsg
        volatile uint32_t FMI;          //< index of filter
    };
     union
    {
        volatile uint8_t padding2[4];   //< padding TxMsg to RxMsg
        volatile uint32_t FIFONumber;   //< receive FIFO number
    };
} hal_based_canmsg_t;

//  !!!!!!!! New API structures use ONLY with "Enum container always int option"
/*
    
*/
typedef struct {
    uint32_t StdId;    //< statndard identifier (11 bit, 0..0x7FF)
    uint32_t ExtId;    //< extended identifier (29 bit)
    uint32_t IDE;      //< type of identifier
    uint32_t RTR;      //< type of frame for message
    uint32_t DLC;      //< data length of frame
    union
    {
        FunctionalState TransmitGlobalTime; 
        uint32_t Timestamp;
    };
    union
    {
        uint8_t padding[4];
        uint32_t FilterMatchIndex; 
    };
    
} canmsg_header_t;

typedef struct {
    canmsg_header_t header;
    union
    {
        uint8_t data[8];
        canmsg_data_t dataStruct; 
    };
} new_api_canmsg_t;

// typedef hal_based_canmsg_t item_t;
typedef new_api_canmsg_t item_t;

#ifdef __cplusplus
}
#endif
#endif /* __can_aux_global_H */
