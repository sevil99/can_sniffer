#include "wrapCanMain.h"
#include "serviceMd.h"
#include "serviceParam.h"
#include "can_aux_main.h"
#include "string.h"

// id, им присваиваются значения в зависимости от g_side
volatile uint32_t canGeneralStdId;
volatile uint32_t canNoticeStdId;
volatile uint32_t canServiceStdId;

volatile uint16_t	vtdm_num; // порядковый номер устройства на CAN шине
volatile uint16_t	ecu_num; // порядковый номер устройства на CAN шине
squeue_t *canMain_squeu_Tx;	// ссылка на очередь отправки сообщений
squeue_t *canMain_squeu_Rx;	// ссылка на очередь приема сообщений

void wrapCanMainVTDM_init(uint16_t	_vtdm_num, squeue_t* _can_squeu_Tx, squeue_t* _can_squeu_Rx){
	vtdm_num = _vtdm_num;
	canMain_squeu_Tx = _can_squeu_Tx;
	canMain_squeu_Rx = _can_squeu_Rx;
	switch(vtdm_num){
		case 0:	canGeneralStdId	= CID_VTDMA_GENERAL;
						canNoticeStdId	= CID_VTDMA_NOTICE;
						canServiceStdId	= CID_VTDMA_SERVICE;  break;
		case 1:	canGeneralStdId	= CID_VTDMB_GENERAL;
						canNoticeStdId	= CID_VTDMB_NOTICE;
						canServiceStdId	= CID_VTDMB_SERVICE;  break;
	}		
}

void wrapCanMainECU_init(uint16_t	_ecu_num, squeue_t* _can_squeu_Tx, squeue_t* _can_squeu_Rx){
	ecu_num = _ecu_num;
	canMain_squeu_Tx = _can_squeu_Tx;
	canMain_squeu_Rx = _can_squeu_Rx;
	switch(vtdm_num){
		case 0:	canGeneralStdId	= CID_ECU_GENERAL;
						canNoticeStdId	= CID_ECU_NOTICE;
						canServiceStdId	= CID_ECU_SERVICE;  break;
	}		
}

int32_t parseCanMainMsg(item_t *item);

void canMain_proceedRxMsg(void){   ///> обработка входящих сообщений в CAN
		if(canMain_squeu_Rx->size)
		{
				item_t* msgp = sq_head(canMain_squeu_Rx);
				if(NULL != msgp)
				{
						int ret = parseCanMainMsg(msgp);
//						if((-1) != ret)
						sq_remove_head(canMain_squeu_Rx);
				}
		}	
}

int32_t parseCanMainMsg(item_t *item)	{
	static int32_t dev_num_cdi;
	#ifdef VTDM_CONTROL
	static int32_t dev_num_vtdm;
	#endif
	if(NULL == item)
		return -1;
	dev_num_cdi = -1;
	#ifdef VTDM_CONTROL
	dev_num_vtdm = -1;
	#endif
  switch(item->header.StdId){
				case CID_VTDMA_NOTICE:
				case CID_VTDMA_GENERAL:
				#ifdef VTDM_CONTROL
				case CID_VTDMA_SERVICE:		dev_num_vtdm = 0; 	break;
				case CID_VTDMB_NOTICE:
				case CID_VTDMB_GENERAL:
				case CID_VTDMB_SERVICE:		dev_num_vtdm = 1; 	break;
				#endif
				case CID_CDIA_NOTICE:
				case CID_CDIA_GENERAL:
				case CID_CDIA_SERVICE:		dev_num_cdi = 0; 	break; 
				
				case CID_CDIB_NOTICE:
				case CID_CDIB_GENERAL:
				case CID_CDIB_SERVICE:		dev_num_cdi = 1; 	break;
				
				case CID_CDIC_NOTICE:
				case CID_CDIC_GENERAL:
				case CID_CDIC_SERVICE:		dev_num_cdi = 2; 	break;
				
				case CID_CDID_NOTICE:
				case CID_CDID_GENERAL:
				case CID_CDID_SERVICE:		dev_num_cdi = 3; 	break;				
				
				default:{ 		
					#ifdef VTDM_CONTROL
					dev_num_vtdm =  -1;
					#endif
					dev_num_cdi =  	-1;
				}					
	}
	//Разбираем массив по МРТК
	#ifdef VTDM_CONTROL
	if(dev_num_vtdm >= 0){
		switch(item->dataStruct.identifier.um){
			case CANMSG_VTDM_PING:{
				submoduleVtdmArr[dev_num_vtdm].g.cntrPing++;
				submoduleVtdmArr[dev_num_vtdm].g.tempVal = item->dataStruct.value.f;
				break;
			}
			case CANMSG_VTDM_MODE:{
				submoduleVtdmArr[dev_num_vtdm].g.cntrPing++;
				submoduleVtdmArr[dev_num_vtdm].submodMd = item->dataStruct.value.um[0];
				break;
			}
			case CANMSG_VTDM_ERROR:	{		
				submoduleVtdmArr[dev_num_vtdm].g.cntrPing++;
				submoduleVtdmArr[dev_num_vtdm].submodError = item->dataStruct.value.uw;
				smd_emergencyStop(ERROR_VTDMA, 0);
				break;
			}
			case CANMSG_VTDM_CFG_READY:			{
				serviceDevCfgReadyReceieve(dev_num_vtdm);
				break; 					
			}	
			case CANMSG_VTDM_CFG_PARAMVAL:	{
				serviceDevParamReceieve(dev_num_vtdm, item->dataStruct.code.um, item->dataStruct.value.uw);
				break;
			}
			case CANMSG_VTDM_CFG_CONFIRM:		{
				serviceDevCfgConfirmReceieve();
				break; 				
			}	
			case CANMSG_VTDM_CFG_CRCVAL:		{
				submoduleVtdmArr[dev_num_vtdm].g.cntrPing++;
				submoduleVtdmArr[dev_num_vtdm].prm.crcVal = item->dataStruct.value.uw;
				submoduleVtdmArr[dev_num_vtdm].prm.isCrcValRecieved = true;
				break;
			}	
			case CANMSG_VTDM_STATREG_VAL:	{
				STATREG_WRITE_UINT32(item->dataStruct.code.um, item->dataStruct.value.uw);
				break;
			}			
			default: 		return -1;
		}	
	}
	#endif

	//Разбираем массив по БЗ	
	if(dev_num_cdi >= 0){
		switch(item->dataStruct.identifier.um){
			case CANMSG_CDI_PING:{
				submoduleCdiArr[dev_num_cdi].g.cntrPing++;
				submoduleCdiArr[dev_num_cdi].g.tempVal = item->dataStruct.value.f;
				break;
			}
			case CANMSG_CDI_MODE:{
				submoduleCdiArr[dev_num_cdi].g.cntrPing++;
				submoduleCdiArr[dev_num_cdi].submodMd = (DevModuleMode_t)item->dataStruct.value.um[0];
				break;
			}
			case CANMSG_CDI_FLTCUT:{
				submoduleCdiArr[dev_num_cdi].g.cntrPing++;
				submoduleCdiArr[dev_num_cdi].submodCut = item->dataStruct.value.um[0];
				break;
			}
			case CANMSG_CDI_ERROR:	{		
				submoduleCdiArr[dev_num_cdi].g.cntrPing++;
				submoduleCdiArr[dev_num_cdi].submodError = (ModuleError_cdi_t)item->dataStruct.value.uw;
				switch(dev_num_cdi){
					case 0	: smd_emergencyStop(ERROR_CDIA1, 0); break;
					case 1	: smd_emergencyStop(ERROR_CDIA2, 0); break;
					case 2	: smd_emergencyStop(ERROR_CDIB1, 0); break;
					case 3	: smd_emergencyStop(ERROR_CDIB2, 0); break;
					default	: smd_emergencyStop(ERROR_CDIA1, 0); break;
				}  
			}
			case CANMSG_CDI_CFG_READY:			{
				serviceDevCfgReadyReceieve(dev_num_cdi);
				break; 					
			}	
			case CANMSG_CDI_CFG_PARAMVAL:	{
				serviceDevParamReceieve(dev_num_cdi, item->dataStruct.code.um, item->dataStruct.value.uw);
				break;
			}
			case CANMSG_CDI_CFG_CONFIRM:		{
				serviceDevCfgConfirmReceieve();
				break; 				
			}	
			case CANMSG_CDI_CFG_CRCVAL:		{
				submoduleCdiArr[dev_num_cdi].g.cntrPing++;
				submoduleCdiArr[dev_num_cdi].prm.crcVal = item->dataStruct.value.uw;
				submoduleCdiArr[dev_num_cdi].prm.isCrcValRecieved = true;
				break;
			}				
			default: 		return -1;
		}	
	}	
	
	return 0;
}

//	отправка сообщения об ошибке (в данной функции devNum - номер устройства, например, конфигуратор)
void canMain_sendError(uint16_t  devNum, uint16_t error){
	  static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_ECU_ERR	
    };
		msg.header.StdId = canNoticeStdId;
    msg.dataStruct.code.um 	= devNum;				
    msg.dataStruct.value.um[1] = error;				
		int ret = sq_insert_head(canMain_squeu_Tx, &msg);
		#ifdef DEBUG_SWO
				if(ret < 0){
            TM_SWO_Printf("sq_insert_head error in sendError, ret = %d", ret);
        }
    #endif
}


void canMain_sendPing(float temp){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_ECU_PING	
    };
    msg.header.StdId = canNoticeStdId;
    msg.dataStruct.value.f = temp;	
		int ret = sq_insert_tail(canMain_squeu_Tx, &msg);
    #ifdef DEBUG_SWO
			if(ret < 0){
				TM_SWO_Printf("sq_insert_tail error in sendPing, ret = %d, size = %ui \n", ret, 0);
			}
    #endif
}


void canMain_sendStart(){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_ECU_START	
    };
		smd_resetSubmodMd();
    msg.header.StdId = canGeneralStdId;
		int ret = sq_insert_tail(canMain_squeu_Tx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
        TM_SWO_Printf("sq_insert_tail error in sendStart, ret = %d, size = %ui \n", ret, 0);
      }
   #endif
}


void canMain_sendStop(){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_ECU_STOP	
    };
 		smd_resetSubmodMd();
		msg.header.StdId = canNoticeStdId;
		int ret = sq_insert_tail(canMain_squeu_Tx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
        TM_SWO_Printf("sq_insert_tail error in sendStop, ret = %d, size = %ui \n", ret, 0);
      }
   #endif
}


void canMain_sendDeblock(){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_ECU_DEBLOCK	
    };
		smd_resetSubmodMd();
    msg.header.StdId = canGeneralStdId;
		int ret = sq_insert_tail(canMain_squeu_Tx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
        TM_SWO_Printf("sq_insert_tail error in sendDeblock, ret = %d, size = %ui \n", ret, 0);
      }
   #endif
}

void canMain_sendVtdmServStart(){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_ECU_TO_VTDM_SERV_START	
    };
    msg.header.StdId = canGeneralStdId;
		int ret = sq_insert_tail(canMain_squeu_Tx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
        TM_SWO_Printf("sq_insert_tail error in sendVtdmServStart, ret = %d, size = %ui \n", ret, 0);
      }
   #endif
}

void canMain_sendVtdmServStop(){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_ECU_TO_VTDM_SERV_STOP	
    };
    msg.header.StdId = canGeneralStdId;
		int ret = sq_insert_tail(canMain_squeu_Tx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
        TM_SWO_Printf("sq_insert_tail error in sendVtdmServStop, ret = %d, size = %ui \n", ret, 0);
      }
   #endif
}



void canMain_sendCdiServStart(){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_ECU_TO_CDI_SERV_START	
    };
    msg.header.StdId = canGeneralStdId;
		int ret = sq_insert_tail(canMain_squeu_Tx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
        TM_SWO_Printf("sq_insert_tail error in sendCdiServStart, ret = %d, size = %ui \n", ret, 0);
      }
   #endif
}

void canMain_sendCdiServStop(){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_ECU_TO_CDI_SERV_STOP	
    };
    msg.header.StdId = canGeneralStdId;
		int ret = sq_insert_tail(canMain_squeu_Tx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
        TM_SWO_Printf("sq_insert_tail error in sendCdiServStop, ret = %d, size = %ui \n", ret, 0);
      }
   #endif
}


void canMain_sendMdRequest(){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_ECU_TO_VTDM_MODE_REQ	
    };
    msg.header.StdId = canGeneralStdId;
		int ret = sq_insert_tail(canMain_squeu_Tx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
        TM_SWO_Printf("sq_insert_tail error in sendMdRequest, ret = %d, size = %ui \n", ret, 0);
      }
   #endif
}


void canMain_sendParamCrcRequest(uint16_t devNum){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_CFG_CRCPARAM_REQ	
    };
    msg.header.StdId = canGeneralStdId;
		msg.dataStruct.code.um = devNum;
		int ret = sq_insert_tail(canMain_squeu_Tx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
        TM_SWO_Printf("sq_insert_tail error in sendParamCrcRequest, ret = %d, size = %ui \n", ret, 0);
      }
   #endif
}

void canMain_sendCfgOn(uint16_t devNum){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_CFG_ON	
    };
    msg.header.StdId = canGeneralStdId;
		msg.dataStruct.code.um = devNum;
		int ret = sq_insert_tail(canMain_squeu_Tx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
        TM_SWO_Printf("sq_insert_tail error in sendCfgOn, ret = %d, size = %ui \n", ret, 0);
      }
   #endif
}

void canMain_sendCfgAccept(void){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_CFG_ACCEPTPARAM	
    };
    msg.header.StdId = canGeneralStdId;
		int ret = sq_insert_tail(canMain_squeu_Tx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
        TM_SWO_Printf("sq_insert_tail error in sendCfgAccept, ret = %d, size = %ui \n", ret, 0);
      }
   #endif
}


void canMain_sendWriteParam(uint16_t index, uint32_t value){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_CFG_WRITEPARAM	
    };
    msg.header.StdId = canGeneralStdId;
		msg.dataStruct.code.um = index;
		msg.dataStruct.value.uw = value;
		int ret = sq_insert_tail(canMain_squeu_Tx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
        TM_SWO_Printf("sq_insert_tail error in sendWriteParam, ret = %d, size = %ui \n", ret, 0);
      }
   #endif
}


void canMain_sendOpMode(){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_ECU_OPERATION_MODE	
    };
    msg.header.StdId = canGeneralStdId;
    msg.dataStruct.value.um[0] = smd_budMd; // заменить на md_ecuMode	
		int ret = sq_insert_tail(canMain_squeu_Tx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
        TM_SWO_Printf("sq_insert_tail error in sendOpMode, ret = %d, size = %ui \n", ret, 0);
      }
   #endif
}

void can_sendParamVal(uint16_t paramCode){
/*    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANVLVMSG_CFG_PARAMVAL	
    };
		if(paramCode < PARAM_REG_SIZE){
			msg.header.StdId = can1NoticeStdId;
			msg.dataStruct.code.um	=	paramCode;
			msg.dataStruct.value.uw	=	paramMap.uw[paramCode];
			int ret = sq_insert_tail((squeue_t*)&canVlvTx, &msg);
			#ifndef DEBUG_SWO  
				if(ret < 0){
          TM_SWO_Printf("sq_insert_tail error in sendOpMode, ret = %d", ret);
				}
			#endif
		}*/
}


void can_sendCfgReady(void){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_ECU_DUMMY	
    };
    msg.header.StdId = canNoticeStdId;
		int ret = sq_insert_tail(canMain_squeu_Tx, &msg);
    #ifdef DEBUG_SWO
        if(ret < 0){
            TM_SWO_Printf("sq_insert_tail error in sendCfgReady, ret = %d", ret);
        }
    #endif
}

void can_sendCfgConfirm(void){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_ECU_DUMMY	
    };
    msg.header.StdId = canNoticeStdId;
		int ret = sq_insert_tail(canMain_squeu_Tx, &msg);
    #ifdef DEBUG_SWO
        if(ret < 0){
            TM_SWO_Printf("sq_insert_tail error in sendCfgConfirm, ret = %d", ret);
        }
    #endif
}

void can_sendParamCrcval(void){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_ECU_DUMMY	
    };
    msg.header.StdId = canNoticeStdId;
//		msg.dataStruct.value.uw	=	paramCrc;
		int ret = sq_insert_tail(canMain_squeu_Tx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
          TM_SWO_Printf("sq_insert_tail error in sendParamCrcval, ret = %d", ret);
     }
    #endif
}

