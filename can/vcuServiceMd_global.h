/**
 \file          vcuServiceMd_global.h
 \author        Mikhail Kuniaev
 \date          August, 2023
 \brief         Defines for VCU workmodes and other 
 \note          Only universal for VCU and VTDM defines are placing 
                at this file
 */

#ifndef __vcuServiceMd_global_H
#define __vcuServiceMd_global_H

#ifdef __cplusplus
 extern "C" {
#endif

    
typedef enum	{
	VCU_MD_UNKNOWN = 		0,
	VCU_MD_READY = 			1,
	VCU_MD_RUN 	= 			3,
	VCU_MD_SYNCFAULT = 	4,
	VCU_MD_FAULT = 			5,
	VCU_MD_SWRESET = 		6,
	VCU_MD_INIT = 			8,
} VcuModuleMode_t;
	

#ifdef __cplusplus
}
#endif
#endif /* __vcuServiceMd_global_H */
