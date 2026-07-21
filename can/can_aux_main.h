/**
 \file          can_aux_main.h
 \author        Alexey Evlampjev
 \date          January, 2018
 \brief         Auxiliary defines and functions for Wartsila project CAN bus
 \note          Only universal for all nodes defines and functions are placing 
                at this file
 */

#ifndef __can_aux_main_H_
#define __can_aux_main_H_

#ifdef __cplusplus
 extern "C" {
#endif

#include "can_aux_global.h"

#pragma anon_unions


#if !defined (VALVE_MODULE)
     #define VALVE_MODULE
#endif



#define ENGINE_CONTROL_UNIT
#define VALVE_TIMING_DISTRIBUTION_MODULE
#define CAPASITOR_DISCHARGE_IGNITION




// идентификаторы сообщений (команд) блока управления двигателем
typedef enum
{																													//Data			//	NOTICE/GENERAL/SERVICE	
	CANMSG_ECU_START						= 2,								//------		//	GENERAL	
	CANMSG_ECU_STOP							= 3,								//------		//	NOTICE
	CANMSG_ECU_DEBLOCK					= 4,								//------		//	GENERAL
	CANMSG_ECU_PING											= 5,								//--dddd		//	GENERAL		// dddd - значение температуры мк БУД
	CANMSG_ECU_TEMP 										= CANMSG_ECU_PING,
	CANMSG_ECU_OPERATION_MODE						=	6,								//----nn		//	GENERAL		//  nn - код режима БУД
	CANMSG_ECU_TO_VTDM_MODE_REQ					= 0x11,							//000000		//	GENERAL
	CANMSG_ECU_TO_VTDM_SERV_START				= 0x12,							//000000		//	GENERAL
	CANMSG_ECU_TO_VTDM_SERV_STOP				= 0x13,							//000000		//	GENERAL
	CANMSG_ECU_TO_CDI_SERV_START				= 0x14,							//000000		//	GENERAL
	CANMSG_ECU_TO_CDI_SERV_STOP					= 0x15,							//000000		//	GENERAL
	CANMSG_CFG_ON												= 0x21,							//nn----		//	GENERAL		// nn - номер модуля, переводимого в режим конфигурации
	CANMSG_CFG_WRITEPARAM								= 0x22,							//nndddd		//	SERVICE   // nn - номер параметра, dddd - значение параметра
	CANMSG_CFG_RAEDPARAM								= 0x23,							//nn--NN		//	SERVICE   // nn - номер модуля, NN - номер параметра
	CANMSG_CFG_ACCEPTPARAM							= 0x25,							//------		//	SERVICE
	CANMSG_CFG_CRCPARAM_REQ							= 0x26,							//nn----		//	SERVICE   // nn - номер модуля
	
	CANMSG_ECU_ERR											= 13,								//----nn		//	GENERAL		//  nn - код ошибки БУД
	CANMSG_ECU_DUMMY										= 14								// технологическая заглушка. Позже сделать реальный идентификатор 
} canmsg_ecu_t;


// идентификаторы сообщений (команд) модуля распределения тактирования клапанов
typedef enum{																															//Data			//	NOTICE/GENERAL/SERVICE	
	CANMSG_VTDM_PING 										= 0x5,								//--dddd		//	GENERAL		// dddd - значение температуры мк МРТК
	CANMSG_VTDM_MODE										= 0x1,								//----nn		//	GENERAL		//  nn - код режима МРТК
	CANMSG_VTDM_ERROR										= 0x2,								//NN--nn		//	NOTICE		// nn - номер канала, NN - номер ошибки
	CANMSG_VTDM_CFG_READY								= 0x21,								//------		//	SERVICE
	CANMSG_VTDM_CFG_PARAMVAL						= 0x22,								//nndddd		//	SERVICE   // nn - номер параметра, dddd - значение параметра 
	CANMSG_VTDM_CFG_CONFIRM							= 0x23,								//------		//	SERVICE 
	CANMSG_VTDM_CFG_CRCVAL							= 0x24,								//--dddd		//	SERVICE		//  dddd - значение CRC 
	CANMSG_VTDM_STATREG_VAL							= 0x31,								//nndddd		// SERVICE		// nn - номер регистра, dddd - значение регистра

} canmsg_vtdm_t;


// идентификаторы сообщений(команд) блока зажигания 
typedef enum
{
	CANMSG_CDI_PING 									= 0x5,								//--dddd		//	GENERAL		// dddd - значение температуры мк МРТК
	CANMSG_CDI_MODE										= 0x1,								//----nn		//	GENERAL		//  nn - код режима МРТК
	CANMSG_CDI_ERROR									= 0x2,								//NN--nn		//	NOTICE		// nn - номер канала, NN - номер ошибки
	CANMSG_CDI_FLTCUT									= 0x11,									//----dd		//	GENERAL		// dd - битовое поле обрывов по каждому из каналов
	CANMSG_CDI_CFG_READY							= 0x21,								//------		//	SERVICE
	CANMSG_CDI_CFG_PARAMVAL						= 0x22,								//nndddd		//	SERVICE   // nn - номер параметра, dddd - значение параметра 
	CANMSG_CDI_CFG_CONFIRM						= 0x23,								//------		//	SERVICE 
	CANMSG_CDI_CFG_CRCVAL							= 0x24,								//--dddd		//	SERVICE		//  dddd - значение CRC
} canmsg_cdi_t;


// идентификаторы сообщений (команд) конфигуратора (основного)
typedef enum
{
    CANMSG_CFG1_VCM_VALVETEST_ON			= 5,
    CANMSG_CFG1_VCM_VALVETEST_OFF,
    CANMSG_CFG1_VCM_SWRESET						= 0x000F,
    CANMSG_CFG1_ENUM_TYPE							= 0x00FF + 0x0001
} canmsg_cfg1_t;

#ifdef __cplusplus
}
#endif
#endif /* __can_aux_main_H */
