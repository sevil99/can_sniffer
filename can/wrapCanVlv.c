#include "wrapCanVlv.h"
#include "can_aux_vlv.h"
#include "ModbusRTU.h"
//#include"serviceMd.h"
//#include"serviceParam.h"
#include"squeue.h"
//#include"defines.h"
//#include"serviceParam.h"

#define DEBUG_PRINT_F(val, size, text) {				 \
		if(val < 0){																\
      TM_SWO_Printf("Squeu canVlv Tx insert error in ");	\
			TM_SWO_Printf(text);															\
			TM_SWO_Printf(", ret = %d Squeu size = %d \n", val, size);	\
		}	\
	}		
/*
#define DEBUG_PRINT_F(val, size, text) {				 \
      TM_SWO_Printf("Squeu canVlv Tx insert error in ");	\
			TM_SWO_Printf(text);															\
			TM_SWO_Printf(", ret = %d Squeu size = %d \n", val, size);	\
	}		
*/

// id, им присваиваются значения в зависимости от g_side
volatile uint32_t canVlvGeneralStdId;
volatile uint32_t canVlvNoticeStdId;
volatile uint32_t canVlvServiceStdId;

squeue_t *canVlv_squeu_Tx;	// ссылка на очередь отправки сообщений
squeue_t *canVlv_squeu_Rx;	// ссылка на очередь приема сообщений


void wrapCanVlv_init(squeue_t* _can_squeu_Tx, squeue_t* _can_squeu_Rx){
	//vtdm_num = _vtdm_num;
	canVlv_squeu_Tx = _can_squeu_Tx;
	canVlv_squeu_Rx = _can_squeu_Rx;
	canVlvGeneralStdId 	= KSIVLV_KSIA1_GENERAL;
	canVlvNoticeStdId 	= KSIVLV_KSIA1_NOTICE;
	canVlvServiceStdId 	= KSIVLV_KSIA1_SERVICE; 	
}

