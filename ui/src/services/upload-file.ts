import { upload } from '@/utils/request'
import {
  type UploadFileResponse,
  type UploadFileTextResponse,
  type UploadImageResponse,
} from '@/models/upload-file'

// 上传图片服务
export const uploadImage = (image: File) => {
  // 1.构建表单并添加图片数据
  const formData = new FormData()
  formData.append('file', image)

  // 2.调用upload服务实现图片上传
  return upload<UploadImageResponse>(`/upload-files/image`, {
    data: formData,
  })
}

// 上传文件服务
export const uploadFile = (file: File) => {
  // 1.构建表单并添加图片数据
  const formData = new FormData()
  formData.append('file', file)

  // 2.调用upload服务实现图片上传
  return upload<UploadFileResponse>(`/upload-files/file`, {
    data: formData,
  })
}

// 上传对话附件并解析成文本服务(不落库、不入对象存储，仅用于随消息注入上下文)
export const uploadFileText = (file: File) => {
  // 1.构建表单并添加文件数据
  const formData = new FormData()
  formData.append('file', file)

  // 2.调用upload服务实现附件上传与解析(文本类返回文本，图片/二进制返回地址)
  return upload<UploadFileTextResponse>(`/upload-files/attachment`, {
    data: formData,
  })
}
